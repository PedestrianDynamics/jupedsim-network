# SPDX-License-Identifier: LGPL-3.0-or-later
"""Hydraulic movement relations adapted from the SFPE Handbook.

The relations follow SFPE Handbook Chap. 67 (6th ed.). The stair speed
constant ``k = 51.8 sqrt(T/R)`` m/min follows EvacuatioNZ and the Fire
Engineering Design Guide (EvacuatioNZ Verification v2.11, Sect. 2.1.3,
Eq. 2.1), not SFPE.

Speeds are in m/s, densities in persons/m², specific flows in persons/s per
metre of effective width.
"""

import math
from dataclasses import dataclass, fields
from numbers import Real

import numpy as np

#: Density floor used in speed calculation, not a minimum physical density.
#: An applicability bound of the relation, fixed for every configuration.
MIN_DENSITY = 0.54

#: Boundary layer per side of an opening, zero by definition.
OPENING_BOUNDARY_LAYER = 0.0


@dataclass(frozen=True, slots=True)
class HydraulicParameters:
    """Empirical coefficients of the SFPE model, defaults from the handbook.

    The defaults follow SFPE Handbook Eq. 67.3 (speed-density relation),
    Tables 67.1, 67.2 and 67.5; the stair coefficient follows EvacuatioNZ.
    Changed values are study assumptions, not validated ranges. Jam density
    ``1/a``, peak-flow density ``1/(2a)`` and maximum specific flow
    ``k/(4a)`` are derived and cannot be set.
    """

    speed_density_slope: float = 0.266  # m²/person
    level_speed_constant: float = 84.0 / 60.0  # m/s
    door_specific_flow: float = 1.3  # persons/(m*s); prescribed capacity

    stair_speed_coefficient: float = 51.8  # m/min; EvacuatioNZ
    door_boundary_layer: float = 0.15  # m per side
    stair_boundary_layer: float = 0.15  # m per side

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(f"{field.name} must be a real scalar.")
            try:
                value = float(value)
            except OverflowError:
                raise ValueError(f"{field.name} must be finite.") from None
            if not math.isfinite(value):
                raise ValueError(f"{field.name} must be finite.")
            object.__setattr__(self, field.name, value)
        for name in (
            "speed_density_slope",
            "level_speed_constant",
            "door_specific_flow",
            "stair_speed_coefficient",
        ):
            value = getattr(self, name)
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value}.")
        for name in ("door_boundary_layer", "stair_boundary_layer"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} must be nonnegative, got {value}.")
        self._check_density_floor()
        self._check_door_flow()

    def _check_density_floor(self) -> None:
        a = self.speed_density_slope
        if not math.isfinite(self.jam_density):
            raise ValueError(
                f"speed_density_slope {a} is too small: 1/a must be finite."
            )
        if not self.peak_flow_density >= MIN_DENSITY:
            raise ValueError(
                "speed_density_slope must keep the peak-flow density 1/(2a) "
                f"at or above the density floor {MIN_DENSITY}, so "
                f"a <= {1 / (2 * MIN_DENSITY):.3f}; got {a}."
            )

    def _check_door_flow(self) -> None:
        limit = self.max_specific_flow
        if self.door_specific_flow > limit:
            raise ValueError(
                f"door_specific_flow {self.door_specific_flow} exceeds the "
                f"maximum specific flow k_level/(4a) = {limit:.4g} given by "
                f"level_speed_constant {self.level_speed_constant} and "
                f"speed_density_slope {self.speed_density_slope}."
            )

    @property
    def jam_density(self) -> float:
        """Density at which the linear speed reaches zero, in persons/m²."""
        return 1.0 / self.speed_density_slope

    @property
    def peak_flow_density(self) -> float:
        """Density maximizing the specific flow, in persons/m²."""
        return 1.0 / (2.0 * self.speed_density_slope)

    @property
    def max_specific_flow(self) -> float:
        """Maximum specific flow ``k/(4a)`` of the level relation."""
        return self.level_speed_constant / (4.0 * self.speed_density_slope)


DEFAULT_HYDRAULIC_PARAMETERS = HydraulicParameters()

# Compatibility aliases for callers using the default model.
#: Slope of the linear speed-density relation ``S = k (1 - a D)``.
SPEED_DENSITY_SLOPE = DEFAULT_HYDRAULIC_PARAMETERS.speed_density_slope

#: Speed constant k for level walkways and doorways (84 m/min).
LEVEL_SPEED_CONSTANT = DEFAULT_HYDRAULIC_PARAMETERS.level_speed_constant

#: Prescribed doorway capacity, independent of the speed-density maximum.
DOOR_SPECIFIC_FLOW = DEFAULT_HYDRAULIC_PARAMETERS.door_specific_flow

#: Density at which the speed-density relation reaches zero speed.
JAM_DENSITY = DEFAULT_HYDRAULIC_PARAMETERS.jam_density

#: Density at which the specific flow ``S * D`` reaches its maximum.
PEAK_FLOW_DENSITY = DEFAULT_HYDRAULIC_PARAMETERS.peak_flow_density

#: Empirical stair coefficient in m/min (EvacuatioNZ v2.11, Sect. 2.1.3).
STAIR_SPEED_COEFFICIENT = DEFAULT_HYDRAULIC_PARAMETERS.stair_speed_coefficient

#: Riser range in m of the stairs in SFPE Table 67.2 (6.5-7.5 in).
STAIR_RISER_RANGE = (6.5 * 0.0254, 7.5 * 0.0254)

#: Tread range in m of the stairs in SFPE Table 67.2 (10-13 in).
STAIR_TREAD_RANGE = (10.0 * 0.0254, 13.0 * 0.0254)


def stair_speed_constant(
    riser: float,
    tread: float,
    *,
    parameters: HydraulicParameters = DEFAULT_HYDRAULIC_PARAMETERS,
) -> float:
    """Speed constant k for stairs, ``51.8 * sqrt(tread / riser)`` m/min.

    The closed form is taken from EvacuatioNZ and the Fire Engineering Design
    Guide (Spearpoint, EvacuatioNZ verification v2.11, Sect. 2.1.3, Eq. 2.1).
    SFPE tabulates k only (Table 67.2) and states that stair speed varies
    approximately with ``sqrt(tread / riser)`` for risers of 165-191 mm and
    treads of 254-330 mm (6th ed., p. 2175). This function does not restrict
    riser or tread to that range, but both must be below 1 m, which
    catches values given in mm or cm.

    Arguments:
        riser: riser height in m
        tread: tread depth in m

    Returns:
        k in m/s

    Raises:
        ValueError: riser or tread is not positive, not finite or not
            below 1 m
    """
    if not (riser > 0 and tread > 0):
        raise ValueError(
            f"Riser and tread must be positive, got riser {riser}, tread "
            f"{tread}."
        )
    if not (riser < 1.0 and tread < 1.0):
        raise ValueError(
            "riser and tread are in m and must be below 1 m; got riser "
            f"{riser}, tread {tread} (mm?)."
        )
    return parameters.stair_speed_coefficient * math.sqrt(tread / riser) / 60.0


def max_specific_flow(
    speed_constant: float,
    *,
    parameters: HydraulicParameters = DEFAULT_HYDRAULIC_PARAMETERS,
) -> float:
    """Maximum of ``S(D) * D`` for nonnegative k, ``k/(4a)``, in persons/(m*s).

    This derived flow is independent of the prescribed doorway capacity.
    """
    return speed_constant / (4.0 * parameters.speed_density_slope)


def speed(
    density,
    speed_constant,
    *,
    parameters: HydraulicParameters = DEFAULT_HYDRAULIC_PARAMETERS,
):
    """Congested walking speed ``k (1 - a D)`` with D floored at MIN_DENSITY.

    ``MIN_DENSITY`` is a computational floor, not a minimum physical density.
    At zero density this gives a hydraulic reference speed, not an empirical
    individual free-walking speed. Works element-wise on numpy arrays.
    The result is never negative.
    """
    d = np.maximum(density, MIN_DENSITY)
    return np.maximum(
        speed_constant * (1.0 - parameters.speed_density_slope * d), 0.0
    )


def effective_width(width: float, boundary_layer: float) -> float:
    """Clear width minus a boundary layer on each side."""
    return max(width - 2.0 * boundary_layer, 0.0)
