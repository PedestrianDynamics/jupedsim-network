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

import numpy as np

#: Slope of the linear speed-density relation ``S = k (1 - a D)``.
SPEED_DENSITY_SLOPE = 0.266

#: Below this density the speed is taken as the free-walking speed.
MIN_DENSITY = 0.54

#: Speed constant k for level walkways and doorways (84 m/min).
LEVEL_SPEED_CONSTANT = 84.0 / 60.0

#: Maximum specific flow through doorways.
DOOR_SPECIFIC_FLOW = 1.3

#: Density at which the speed-density relation reaches zero speed.
JAM_DENSITY = 1.0 / SPEED_DENSITY_SLOPE

#: Density at which the specific flow ``S * D`` reaches its maximum.
PEAK_FLOW_DENSITY = 1.0 / (2.0 * SPEED_DENSITY_SLOPE)

#: Riser range in m of the stairs in SFPE Table 67.2 (6.5-7.5 in).
STAIR_RISER_RANGE = (6.5 * 0.0254, 7.5 * 0.0254)

#: Tread range in m of the stairs in SFPE Table 67.2 (10-13 in).
STAIR_TREAD_RANGE = (10.0 * 0.0254, 13.0 * 0.0254)


def stair_speed_constant(riser: float, tread: float) -> float:
    """Speed constant k for stairs, ``51.8 * sqrt(tread / riser)`` m/min.

    The closed form is taken from EvacuatioNZ and the Fire Engineering Design
    Guide (Spearpoint, EvacuatioNZ verification v2.11, Sect. 2.1.3, Eq. 2.1).
    SFPE tabulates k only (Table 67.2) and states that stair speed varies
    approximately with ``sqrt(tread / riser)`` for risers of 165-191 mm and
    treads of 254-330 mm (6th ed., p. 2175). This function does not restrict
    riser or tread to that range.

    Arguments:
        riser: riser height in m
        tread: tread depth in m

    Returns:
        k in m/s
    """
    if riser <= 0 or tread <= 0:
        raise ValueError("Riser and tread must be positive.")
    return 51.8 * math.sqrt(tread / riser) / 60.0


def max_specific_flow(speed_constant: float) -> float:
    """Maximum of ``S(D) * D``, reached at :data:`PEAK_FLOW_DENSITY`."""
    return speed_constant / (4.0 * SPEED_DENSITY_SLOPE)


def speed(density, speed_constant):
    """Congested walking speed ``k (1 - a D)`` with D floored at 0.54/m².

    Works element-wise on numpy arrays. The result is never negative.
    """
    d = np.maximum(density, MIN_DENSITY)
    return np.maximum(speed_constant * (1.0 - SPEED_DENSITY_SLOPE * d), 0.0)


def effective_width(width: float, boundary_layer: float) -> float:
    """Clear width minus a boundary layer on each side."""
    return max(width - 2.0 * boundary_layer, 0.0)
