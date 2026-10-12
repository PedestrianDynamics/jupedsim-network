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


@dataclass(frozen=True, slots=True)
class HydraulicParameters:
    """Empirical parameters and density-floor assumption of the SFPE model.

    Units are documented per field. The stair coefficient retains m/min from
    its reference and is converted to m/s by the stair relation. Derived
    densities describe the implemented relation, not a scientifically validated
    applicability range for custom parameters.
    """

    speed_density_slope: float = 0.266  # m²/person
    min_density: float = 0.54  # persons/m²; density floor in speed calculation
    level_speed_constant: float = 84.0 / 60.0  # m/s
    door_specific_flow: float = 1.3  # persons/(m*s); prescribed capacity

    stair_speed_coefficient: float = 51.8  # m/min; EvacuatioNZ
    door_boundary_layer: float = 0.15  # m per side
    opening_boundary_layer: float = 0.0  # m per side
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
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        for name in (
            "door_boundary_layer",
            "opening_boundary_layer",
            "stair_boundary_layer",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative.")
        if not math.isfinite(self.jam_density):
            raise ValueError(
                "speed_density_slope must give a finite jam_density."
            )
        if not math.isfinite(self.min_density) or not (
            0 <= self.min_density < self.jam_density
        ):
            raise ValueError(
                "min_density must be finite and in [0, jam_density)."
            )

    @property
    def jam_density(self) -> float:
        """Density at which the linear speed reaches zero, in persons/m²."""
        return 1.0 / self.speed_density_slope

    @property
    def peak_flow_density(self) -> float:
        """Density maximizing flow with the density floor, in persons/m²."""
        return max(self.min_density, self.jam_density / 2.0)


# Identifies the equations, units and resolution rules, independently of JSON schema.
HYDRAULIC_MODEL_VERSION = "1"

DEFAULT_HYDRAULIC_PARAMETERS = HydraulicParameters()

# Compatibility aliases for callers using the default model.
#: Slope of the linear speed-density relation ``S = k (1 - a D)``.
SPEED_DENSITY_SLOPE = DEFAULT_HYDRAULIC_PARAMETERS.speed_density_slope

#: Density floor used in speed calculation, not a minimum physical density.
MIN_DENSITY = DEFAULT_HYDRAULIC_PARAMETERS.min_density

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
    """Maximum of ``S(D) * D`` for nonnegative k, in persons/(m*s).

    The analytical maximum k/(4a) applies when the unconstrained optimum
    lies above the density floor; otherwise the maximum is at the floor.
    This derived flow is independent of the prescribed doorway capacity.
    """
    a = parameters.speed_density_slope
    if parameters.min_density <= parameters.jam_density / 2.0:
        denominator = 4.0 * a
        if math.isfinite(denominator):
            return speed_constant / denominator
        # Avoid an overflowing intermediate when the quotient is representable.
        return (speed_constant / a) / 4.0
    d = parameters.peak_flow_density
    return speed_constant * (1.0 - a * d) * d


def speed(
    density,
    speed_constant,
    *,
    parameters: HydraulicParameters = DEFAULT_HYDRAULIC_PARAMETERS,
):
    """Congested walking speed ``k (1 - a D)`` with D floored at min_density.

    ``min_density`` is a computational floor, not a minimum physical density.
    At zero density this gives a hydraulic reference speed, not an empirical
    individual free-walking speed. Works element-wise on numpy arrays.
    The result is never negative.
    """
    d = np.maximum(density, parameters.min_density)
    return np.maximum(
        speed_constant * (1.0 - parameters.speed_density_slope * d), 0.0
    )


def effective_width(width: float, boundary_layer: float) -> float:
    """Clear width minus a boundary layer on each side."""
    return max(width - 2.0 * boundary_layer, 0.0)
