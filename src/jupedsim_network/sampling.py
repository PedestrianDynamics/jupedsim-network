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
    """Base class, truncated to ``[lower, upper]``.

    The values have the unit of the quantity sampled (persons for
    ``count``, s for ``pre_movement``, m/s for ``speed``, m for
    ``start_distance``).

    Attributes:
        lower: lower bound, in the unit of the quantity sampled. Values
            outside ``[lower, upper]`` are drawn again up to 100 times,
            then clipped to the bounds. The default 0 keeps every value
            non-negative; ``None`` removes the bound.
        upper: upper bound, in the unit of the quantity sampled; values
            above it are drawn again as for ``lower``. ``None`` for no
            upper bound.
    """

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
    """Always ``value``.

    Attributes:
        value: the value returned every time; a value outside
            ``[lower, upper]`` is clipped to the bound, so ``-5`` gives 0
            with the default ``lower``
    """

    value: float

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

    def _draw(self, rng, size):
        return self.alpha * rng.weibull(self.beta, size)


def as_distribution(value) -> Distribution:
    """Wrap plain numbers in :class:`Fixed`."""
    if isinstance(value, Distribution):
        return value
    return Fixed(float(value))
