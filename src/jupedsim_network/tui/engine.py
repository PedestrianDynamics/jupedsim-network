# SPDX-License-Identifier: LGPL-3.0-or-later
"""The engine thread: every call into the package, one at a time (design §2.4).

``scenario.attempt`` swaps process-wide warning state while it runs. Two
calls that overlap on two threads can therefore lose warnings or leave a
stale recorder installed (QA-I5), so validation, save, check and run all
go through one long-lived thread that takes jobs from a FIFO queue. The
thread also installs a ``showwarning`` of its own while it lives: a
warning raised on another thread (Textual's) during a job is logged in
:attr:`Engine.foreign` instead of being printed over the screen.

Each job returns one event, which is handed to ``post`` on the engine
thread; the app queues it for its own thread. Imports no Textual.
"""

import functools
import queue
import threading
import time
import traceback
import warnings
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from jupedsim_network import cli_init, cli_run
from jupedsim_network.cli_run import RunCancelled
from jupedsim_network.tui import netview

THREAD_NAME = "jupedsim-network-engine"
PROG = "jupedsim-network"
# Foreign warnings kept for the log; older ones are dropped.
MAX_FOREIGN = 200


# Events


@dataclass(frozen=True)
class Validated:
    gen: int
    error_path: str | None = None
    message: str = ""
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Opened:
    path: str | None
    doc: dict | None
    error: str = ""
    example: str | None = None


@dataclass(frozen=True)
class Saved:
    path: str
    doc: dict | None
    error: str = ""


@dataclass(frozen=True)
class Checked:
    path: str
    # (stream, line) in the order the CLI prints them
    lines: tuple[tuple[str, str], ...]
    status: int
    error_path: str | None = None
    routes: netview.Routes | None = None

    def stream(self, name: str) -> list[str]:
        return [text for where, text in self.lines if where == name]


@dataclass(frozen=True)
class Progress:
    phase: str  # "single run" or "monte carlo"
    done: int
    runs: int | None


@dataclass(frozen=True)
class RunFinished:
    path: str
    out: str
    status: int | None  # the CLI's exit status; None: cancelled
    stdout: tuple[str, ...] = ()
    stderr: tuple[str, ...] = ()
    files: dict[str, str] = field(default_factory=dict)
    done: int = 0
    runs: int | None = None
    phase: str = "single run"
    error_path: str | None = None
    routes: netview.Routes | None = None


@dataclass(frozen=True)
class Failed:
    """A bug: any exception that is not the scenario's own error."""

    what: str
    traceback: str


# The engine


class Engine:
    """One thread, one job at a time, in the order submitted.

    A job is a callable taking the engine and returning an event. A job
    submitted with a ``key`` replaces the one of the same key that is
    still waiting (validation is coalesced). :meth:`stop` drops the jobs
    that are still waiting.
    """

    def __init__(self, throttle: float = 0.1, clock=time.monotonic) -> None:
        self.throttle = throttle
        self.clock = clock
        # The cancel event of the run submitted last (each run has its own).
        self.cancel_event = threading.Event()
        self.foreign: list[str] = []
        self._queue: queue.Queue = queue.Queue()
        self._latest: dict[str, int] = {}
        self._seq = 0
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._previous = None
        self.busy = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._previous = warnings.showwarning
        warnings.showwarning = self._log_foreign
        self._thread = threading.Thread(
            target=self._loop, name=THREAD_NAME, daemon=True
        )
        self._thread.start()

    def submit(self, job, post, key: str | None = None) -> None:
        with self._lock:
            self._seq += 1
            if key is not None:
                self._latest[key] = self._seq
            if hasattr(job, "cancel_event"):
                self.cancel_event = job.cancel_event
            self._queue.put((self._seq, key, job, post))

    def cancel(self) -> None:
        """Cancel the run submitted last, also while it waits in the queue.

        It stops at the next realisation, or before it writes; a run
        submitted later has an event of its own and is not cancelled.
        """
        self.cancel_event.set()

    def stop(self, timeout: float = 30.0) -> None:
        """Drop waiting jobs, wait for the current one, restore warnings."""
        self._drain()
        self.cancel_event.set()
        if self._thread is not None:
            self._queue.put(None)
            self._thread.join(timeout)
        if warnings.showwarning == self._log_foreign:
            warnings.showwarning = self._previous

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return
            self._queue.task_done()

    def _log_foreign(
        self, message, category, filename, lineno, file=None, line=None
    ):
        self.foreign.append(f"{category.__name__}: {message}")
        del self.foreign[:-MAX_FOREIGN]

    @property
    def idle(self) -> bool:
        """No job waiting or running."""
        return self._queue.unfinished_tasks == 0

    def _loop(self) -> None:
        while self._next():
            pass

    def _next(self) -> bool:
        """Run the next job; False at the end (``stop``)."""
        item = self._queue.get()
        try:
            return item is not None and self._handle(*item)
        finally:
            self._queue.task_done()

    def _handle(self, seq: int, key: str | None, job, post) -> bool:
        if key is None or self._latest.get(key) == seq:
            post(self._call(job))
        return True

    def _call(self, job):
        self.busy = True
        try:
            return job(self)
        except Exception:
            return Failed(getattr(job, "what", "job"), traceback.format_exc())
        finally:
            self.busy = False


# Jobs (each runs on the engine thread)


def _job(what: str):
    """Name a job for the internal-error report."""

    def name(fn):
        fn.what = what
        return fn

    return name


def _load(path: str, command: str):
    """The scenario, or the CLI's error line and the error (``cli._load``).

    The error line is "" when the scenario loaded.
    """
    from jupedsim_network.scenario import ScenarioError, load_scenario

    try:
        return load_scenario(path), "", None
    except ScenarioError as exc:
        return None, f"{PROG} {command}: error: {path}: {exc}", exc
    except OSError as exc:
        return (
            None,
            f"{PROG} {command}: error: cannot read {path}: {exc.strerror or exc}",
            None,
        )


def validate(gen: int, doc: dict):
    """Check and build ``doc`` (no trial run)."""

    @_job("validate")
    def job(engine):
        from jupedsim_network.scenario import ScenarioError, scenario_from_dict

        try:
            built = scenario_from_dict(doc)
        except ScenarioError as exc:
            return Validated(gen, exc.path, exc.message)
        return Validated(gen, warnings=built.warnings)

    return job


def open_file(path: str):
    @_job("open")
    def job(engine):
        from jupedsim_network.scenario import ScenarioError, load_scenario

        try:
            loaded = load_scenario(path)
        except ScenarioError as exc:
            return Opened(path, None, f"{path}: {exc}")
        except OSError as exc:
            return Opened(
                path, None, f"cannot read {path}: {exc.strerror or exc}"
            )
        return Opened(path, loaded.to_dict())

    return job


def open_example(name: str):
    """A packaged example through the loader's own parse step; unsaved."""

    @_job("example")
    def job(engine):
        from jupedsim_network.scenario import load_scenario

        files = resources.files("jupedsim_network") / "scenarios"
        with resources.as_file(files / cli_init.EXAMPLES[name]) as packaged:
            loaded = load_scenario(packaged)
        return Opened(None, loaded.to_dict(), example=name)

    return job


def save(doc: dict, path: str):
    """``save_scenario`` then a reload, so the TUI shows what is on disk."""

    @_job("save")
    def job(engine):
        from jupedsim_network.scenario import (
            ScenarioError,
            load_scenario,
            save_scenario,
        )

        try:
            save_scenario(doc, path)
            return Saved(path, load_scenario(path).to_dict())
        except ScenarioError as exc:
            return Saved(path, None, f"Cannot save: {exc}")
        except OSError as exc:
            return Saved(
                path, None, f"Cannot write {path}: {exc.strerror or exc}"
            )

    return job


def check(path: str):
    """What ``jupedsim-network check PATH`` prints, line for line."""

    @_job("check")
    def job(engine):
        from jupedsim_network.scenario import ScenarioError

        loaded, error, exc = _load(path, "check")
        if loaded is None:
            where = None if exc is None else exc.path
            return Checked(path, (("stderr", error),), 1, where)
        warned = list(loaded.warnings)
        lines = [("stdout", t) for t in cli_run.check_lines(loaded, path)]
        routes = _routes(loaded.simulation)
        try:
            seed, trial = cli_run.trial(loaded, warned)
        except ScenarioError as exc:
            lines += _stderr(cli_run.warning_lines(warned))
            lines.append(("stderr", f"{PROG} check: error: {path}: {exc}"))
            return Checked(path, tuple(lines), 1, exc.path, routes)
        lines += _stderr(cli_run.warning_lines(warned))
        lines.append(("stdout", cli_run.run_line("Trial run", seed, trial)))
        if not _finite(trial):
            return Checked(path, tuple(lines), 2, None, routes)
        lines.append(("stdout", "The scenario is valid."))
        return Checked(path, tuple(lines), 0, None, routes)

    return job


def _routes(sim) -> netview.Routes | None:
    """The route tree; ``None`` if the network has none (a tied cycle)."""
    try:
        return netview.build(sim)
    except RuntimeError:
        return None


def _finite(result) -> bool:
    import math

    return math.isfinite(result.evacuation_time)


def _stderr(lines: list[str]) -> list[tuple[str, str]]:
    return [("stderr", line) for line in lines]


def run(path: str, out: str, single: bool, post):
    """``jupedsim-network run PATH -o OUT [--no-monte-carlo]``, cancellable.

    The run has its own cancel event, created here, when it is
    submitted: a cancel confirmed while the run still waits in the queue
    holds, and a cancel of an earlier run never reaches it (QA2-B1). The
    event is checked before the run starts, at every realisation of the
    Monte Carlo set and once after the runs, before anything is written
    (model review I4); a cancelled run writes nothing.
    """
    cancel = threading.Event()

    @_job("run")
    def job(engine):
        if cancel.is_set():
            return RunFinished(path, out, None, phase="queued")
        loaded, error, exc = _load(path, "run")
        if loaded is None:
            where = None if exc is None else exc.path
            return RunFinished(path, out, 1, stderr=(error,), error_path=where)
        settings = None if single else loaded.monte_carlo
        runs = None if settings is None else settings.get("runs")
        state = {"done": 0, "phase": "single run", "posted": -1.0}
        post(Progress("single run", 0, runs))
        progress = functools.partial(_progress, cancel, engine, post, state)
        return _execute(
            cancel, loaded, path, out, single, progress, state, runs
        )

    setattr(job, "cancel_event", cancel)  # read by Engine.submit
    return job


def _progress(cancel, engine, post, state, done: int, runs: int) -> None:
    """The ``run_many`` callback: cancel check every time, posts throttled."""
    if cancel.is_set():
        raise RunCancelled
    state["done"], state["phase"] = done, "monte carlo"
    now = engine.clock()
    if done == runs or now - state["posted"] >= engine.throttle:
        state["posted"] = now
        post(Progress("monte carlo", done, runs))


def _execute(cancel, loaded, path, out, single, progress, state, runs):
    from jupedsim_network.scenario import ScenarioError

    warned = list(loaded.warnings)
    overrides = cli_run.Overrides(no_monte_carlo=single)
    cancelled = RunFinished(path, out, None, runs=runs)
    try:
        outcome = cli_run.execute(loaded, overrides, warned, progress)
        if cancel.is_set():
            raise RunCancelled
    except RunCancelled:
        return _cancelled(cancelled, state)
    except ScenarioError as exc:
        stderr = (
            *cli_run.warning_lines(warned),
            f"{PROG} run: error: {path}: {exc}",
        )
        return RunFinished(path, out, 1, stderr=stderr, error_path=exc.path)
    files = cli_run.result_files(loaded, outcome, path, warned)
    stderr = tuple(cli_run.warning_lines(warned))
    try:
        cli_run.write(Path(out), files)
    except OSError as exc:
        where = exc.filename or Path(out)
        line = f"{PROG} run: error: cannot write {where}: {exc.strerror or exc}"
        return RunFinished(path, out, 1, stderr=(*stderr, line))
    stdout = (
        *cli_run.report_lines(loaded, outcome, path),
        f"Wrote {Path(out)}/: {', '.join(files)}",
    )
    status = 2 if cli_run.incomplete(outcome) else 0
    return RunFinished(
        path,
        out,
        status,
        stdout,
        stderr,
        files,
        state["done"],
        runs,
        state["phase"],
        routes=_routes(loaded.simulation),
    )


def _cancelled(base: RunFinished, state: dict) -> RunFinished:
    return RunFinished(
        base.path,
        base.out,
        None,
        done=state["done"],
        runs=base.runs,
        phase=state["phase"],
    )
