# SPDX-License-Identifier: LGPL-3.0-or-later
"""Hypothesis profiles.

``pr`` (the default) is derandomized, so an unrelated change cannot fail
on a new random example. The scheduled job selects ``fuzz`` with
``--hypothesis-profile=fuzz`` and runs the tests marked ``fuzz``.
"""

from hypothesis import HealthCheck, settings

_COMMON = dict(
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.register_profile(
    "pr", derandomize=True, max_examples=25, database=None, **_COMMON
)
settings.register_profile("fuzz", max_examples=2000, **_COMMON)
settings.load_profile("pr")
