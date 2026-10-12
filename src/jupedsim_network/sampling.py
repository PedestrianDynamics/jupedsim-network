# SPDX-License-Identifier: LGPL-3.0-or-later
"""Random distributions for network model inputs.

Every distribution is truncated to ``[lower, upper]``. Values outside the
range are redrawn a limited number of times and then clipped, so sampling
always terminates.
"""

import math
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

_MAX_REDRAWS = 100


@dataclass(frozen=True, kw_only=True)
class Distribution:
    """Base class, truncated to ``[lower, upper]``.

    The values have the unit of the quantity sampled (persons for
    ``count``, s for ``pre_movement``, m/s for ``speed``, m for
    ``start_distance``).

    Attributes:
        lower: lower bound, in the unit of the quantity sampled. Sampled
            values outside ``[lower, upper]`` are drawn again up to 100
            times, then clipped to the bounds. The default 0 keeps every
            value non-negative; ``None`` removes the bound. ``lower``
            must not exceed ``upper``.
        upper: upper bound, in the unit of the quantity sampled; values
            above it are drawn again as for ``lower``. ``None`` for no
            upper bound.

    Raises:
        ValueError: a bound or parameter is not finite, ``lower`` exceeds
            ``upper``, or a parameter lies outside its valid range
    """

    lower: float | None = 0.0
    upper: float | None = None

    # Names of the parameters each subclass requires to be finite.
    _parameters: ClassVar[tuple[str, ...]] = ()

    def __post_init__(self) -> None:
        for name in ("lower", "upper"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(
                    f"{name} must be a finite number or None, got {value}."
                )
        bounded = self.lower is not None and self.upper is not None
        if bounded and self.lower > self.upper:
            raise ValueError(
                f"lower {self.lower} is greater than upper {self.upper}."
            )
        for name in self._parameters:
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite, got {value}.")
        self._check_parameters()

    def _check_parameters(self) -> None:
        """Hook for parameter ranges numpy does not reject itself."""

    def sample(self, rng: np.random.Generator, size: int) -> np.ndarray:
        values = np.asarray(self._draw(rng, size), dtype=float)
        for _ in range(_MAX_REDRAWS):
            outside = self._outside(values)
            if not outside.any():
                return values
            values[outside] = self._draw(rng, int(outside.sum()))
        return np.clip(values, self.lower, self.upper)

    def _outside(self, values: np.ndarray) -> np.ndarray:
        outside = np.zeros(values.shape, dtype=bool)
        if self.lower is not None:
            outside |= values < self.lower
        if self.upper is not None:
            outside |= values > self.upper
        return outside

    def _draw(self, rng: np.random.Generator, size: int) -> np.ndarray:
        raise NotImplementedError


@dataclass(frozen=True)
class Fixed(Distribution):
    """Always ``value``.

    Attributes:
        value: the value returned every time; it must lie inside
            ``[lower, upper]``, so ``Fixed(-5)`` raises ``ValueError``
            with the default ``lower`` of 0
    """

    value: float
    _parameters = ("value",)

    def _check_parameters(self) -> None:
        if not self._outside(np.array([self.value], dtype=float)).any():
            return
        raise ValueError(
            f"Fixed value {self.value} lies outside [lower, upper] = "
            f"[{self.lower}, {self.upper}]."
        )

    def _draw(self, rng, size):
        return np.full(size, self.value, dtype=float)


@dataclass(frozen=True)
class Uniform(Distribution):
    """Uniform between ``minimum`` and ``maximum``.

    Attributes:
        minimum: smallest value
        maximum: largest value
    """

    minimum: float
    maximum: float
    _parameters = ("minimum", "maximum")

    def _draw(self, rng, size):
        return rng.uniform(self.minimum, self.maximum, size)


@dataclass(frozen=True)
class Normal(Distribution):
    """Normal (Gaussian), before truncation to ``[lower, upper]``.

    Attributes:
        mean: mean before truncation
        std: standard deviation before truncation
    """

    mean: float
    std: float
    _parameters = ("mean", "std")

    def _draw(self, rng, size):
        return rng.normal(self.mean, self.std, size)


@dataclass(frozen=True)
class LogNormal(Distribution):
    """Log-normal given by the mean and standard deviation of the variable.

    Attributes:
        mean: mean of the variable itself, not of its logarithm, before
            truncation
        std: standard deviation of the variable itself, before truncation
    """

    mean: float
    std: float
    _parameters = ("mean", "std")

    def _check_parameters(self) -> None:
        if self.std < 0:
            raise ValueError(f"std must be >= 0, got {self.std}.")

    def _draw(self, rng, size):
        sigma2 = math.log(1.0 + (self.std / self.mean) ** 2)
        mu = math.log(self.mean) - 0.5 * sigma2
        return rng.lognormal(mu, math.sqrt(sigma2), size)


@dataclass(frozen=True)
class Triangular(Distribution):
    """Triangular between ``minimum`` and ``maximum``.

    Attributes:
        minimum: smallest value
        mode: most likely value
        maximum: largest value
    """

    minimum: float
    mode: float
    maximum: float
    _parameters = ("minimum", "mode", "maximum")

    def _draw(self, rng, size):
        return rng.triangular(self.minimum, self.mode, self.maximum, size)


@dataclass(frozen=True)
class Weibull(Distribution):
    """Weibull with scale ``alpha`` and shape ``beta``.

    Attributes:
        alpha: scale, in the unit of the quantity sampled
        beta: shape, dimensionless
    """

    alpha: float
    beta: float
    _parameters = ("alpha", "beta")

    def _check_parameters(self) -> None:
        if self.alpha > 0 and self.beta > 0:
            return
        raise ValueError(
            "Weibull alpha and beta must be positive, got "
            f"{self.alpha}, {self.beta}."
        )

    def _draw(self, rng, size):
        return self.alpha * rng.weibull(self.beta, size)


def as_distribution(value) -> Distribution:
    """Wrap plain numbers in :class:`Fixed`."""
    if isinstance(value, Distribution):
        return value
    return Fixed(float(value))
