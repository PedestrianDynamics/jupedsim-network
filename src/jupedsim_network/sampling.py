# SPDX-License-Identifier: LGPL-3.0-or-later
"""Random distributions for network model inputs.

Every distribution is truncated to ``[lower, upper]``. Values outside the
range are redrawn a limited number of times and then clipped, so sampling
always terminates.
"""

import math
from dataclasses import dataclass

import numpy as np

_MAX_REDRAWS = 100


@dataclass(frozen=True, kw_only=True)
class Distribution:
    """Base class, truncated to ``[lower, upper]``."""

    lower: float | None = 0.0
    upper: float | None = None

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
    value: float

    def _draw(self, rng, size):
        return np.full(size, self.value, dtype=float)


@dataclass(frozen=True)
class Uniform(Distribution):
    minimum: float
    maximum: float

    def _draw(self, rng, size):
        return rng.uniform(self.minimum, self.maximum, size)


@dataclass(frozen=True)
class Normal(Distribution):
    mean: float
    std: float

    def _draw(self, rng, size):
        return rng.normal(self.mean, self.std, size)


@dataclass(frozen=True)
class LogNormal(Distribution):
    """Log-normal given by the mean and standard deviation of the variable."""

    mean: float
    std: float

    def _draw(self, rng, size):
        sigma2 = math.log(1.0 + (self.std / self.mean) ** 2)
        mu = math.log(self.mean) - 0.5 * sigma2
        return rng.lognormal(mu, math.sqrt(sigma2), size)


@dataclass(frozen=True)
class Triangular(Distribution):
    minimum: float
    mode: float
    maximum: float

    def _draw(self, rng, size):
        return rng.triangular(self.minimum, self.mode, self.maximum, size)


@dataclass(frozen=True)
class Weibull(Distribution):
    """Weibull with scale ``alpha`` and shape ``beta``."""

    alpha: float
    beta: float

    def _draw(self, rng, size):
        return self.alpha * rng.weibull(self.beta, size)


def as_distribution(value) -> Distribution:
    """Wrap plain numbers in :class:`Fixed`."""
    if isinstance(value, Distribution):
        return value
    return Fixed(float(value))
