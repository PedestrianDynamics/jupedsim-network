# SPDX-License-Identifier: LGPL-3.0-or-later
"""Analytical configuration checks, independent of routing/flow allocation."""

import copy
import dataclasses
import math

import numpy as np
import pytest

from jupedsim_network import (
    HydraulicParameters,
    Network,
    NetworkSimulation,
    Population,
    Scenario,
    ScenarioError,
    hydraulic,
    load_scenario,
    routing_costs,
    save_scenario,
    scenario_from_dict,
)
from jupedsim_network.simulation import _Run

DEFAULT = HydraulicParameters()


@pytest.mark.parametrize(
    "field,value",
    [
        ("speed_density_slope", 0),
        ("speed_density_slope", -0.1),
        ("speed_density_slope", 5e-324),
        ("min_density", -0.1),
        ("min_density", DEFAULT.jam_density),
        ("min_density", DEFAULT.jam_density + 1),
        ("level_speed_constant", 0),
        ("door_specific_flow", 0),
        ("stair_speed_coefficient", -1),
        ("door_boundary_layer", -0.1),
        ("opening_boundary_layer", -0.1),
        ("stair_boundary_layer", -0.1),
    ],
)
def test_parameter_domain(field, value):
    with pytest.raises(ValueError, match=field):
        dataclasses.replace(DEFAULT, **{field: value})


@pytest.mark.parametrize("field", [f.name for f in dataclasses.fields(DEFAULT)])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, [], {}])
def test_all_parameters_are_finite_immutable_scalars(field, value):
    with pytest.raises(ValueError, match=field):
        dataclasses.replace(DEFAULT, **{field: value})


@pytest.mark.parametrize(
    "floor,peak,flow", [(0, 2, 2), (1, 2, 2), (2, 2, 2), (3, 3, 1.5)]
)
def test_density_floor_peak_and_flow_are_piecewise_consistent(
    floor, peak, flow
):
    parameters = HydraulicParameters(
        speed_density_slope=0.25, min_density=floor
    )
    assert parameters.jam_density == 4
    assert parameters.peak_flow_density == peak
    assert hydraulic.max_specific_flow(2, parameters=parameters) == flow
    assert hydraulic.speed(0, 2, parameters=parameters) == 2 * (
        1 - 0.25 * floor
    )
    assert hydraulic.speed(4, 2, parameters=parameters) == 0
    densities = np.linspace(0, 4, 1001)
    flows = densities * hydraulic.speed(densities, 2, parameters=parameters)
    assert np.max(flows) == pytest.approx(flow)


def room_network(parameters=None):
    net = Network(parameters=parameters)
    net.add_room("room", area=100)
    net.add_safe("safe")
    net.connect("room", "safe", width=10, length=12)
    return net


@pytest.mark.parametrize(
    "change",
    [
        {},
        {"speed_density_slope": 0.2},
        {"min_density": 1.0},
        {"level_speed_constant": 1.0},
    ],
)
def test_level_speed_sensitivity_reaches_routing_and_movement(change):
    parameters = dataclasses.replace(DEFAULT, **change)
    net = room_network(parameters)
    expected_speed = parameters.level_speed_constant * (
        1 - parameters.speed_density_slope * parameters.min_density
    )
    expected_time = 12 / expected_speed
    assert net.node("room").speed_constant == parameters.level_speed_constant
    costs = routing_costs.edge_costs(
        net.nodes,
        net.links,
        "shortest_free_flow_time",
        parameters=net.parameters,
    )
    assert costs == pytest.approx([expected_time])
    sim = NetworkSimulation(net, [Population("room", 1, speed=10)], dt=0.01)
    assert sim.run(seed=1).evacuation_time == pytest.approx(
        expected_time, abs=0.02
    )
    assert routing_costs.edge_costs(
        net.nodes, net.links, "shortest_distance"
    ) == [12]


@pytest.mark.parametrize(
    "kind,field",
    [
        ("door", "door_boundary_layer"),
        ("opening", "opening_boundary_layer"),
        ("stair", "stair_boundary_layer"),
    ],
)
def test_boundary_defaults_and_explicit_zero_override(kind, field):
    parameters = dataclasses.replace(DEFAULT, **{field: 0.25})
    net = Network(parameters=parameters)
    net.add_room("room", area=20)
    net.add_stair("stair", area=20, riser=0.18, tread=0.28)
    default = net.connect("room", "stair", kind=kind, width=2, specific_flow=2)[
        0
    ]
    explicit = net.connect(
        "room", "stair", kind=kind, width=2, specific_flow=2, boundary_layer=0
    )[0]
    assert default.capacity == 3
    assert explicit.capacity == 4
    assert net._inputs[-1][1]["boundary_layer"] == 0


@pytest.mark.parametrize("kind", ["door", "opening", "stair"])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        {},
        {"door_specific_flow": 2},
        {"stair_speed_coefficient": 60},
        {"speed_density_slope": 0.2},
        {"min_density": 2.5},
    ],
)
def test_stair_level_capacity_rule_and_local_flow_override(
    kind, reverse, change
):
    parameters = dataclasses.replace(DEFAULT, **change)
    net = Network(parameters=parameters)
    net.add_room("level", area=20)
    stair = net.add_stair("stair", area=20, riser=0.18, tread=0.28)
    k = parameters.stair_speed_coefficient * math.sqrt(0.28 / 0.18) / 60
    assert stair.speed_constant == k
    endpoints = ("stair", "level") if reverse else ("level", "stair")
    links = net.connect(*endpoints, kind=kind, width=2, boundary_layer=0)
    peak = max(parameters.min_density, 1 / (2 * parameters.speed_density_slope))
    stair_flow = k * peak * (1 - parameters.speed_density_slope * peak)
    flow = stair_flow if kind == "stair" else parameters.door_specific_flow
    assert [link.capacity for link in links] == pytest.approx([2 * flow] * 2)
    override = net.connect(
        *endpoints, kind=kind, width=2, boundary_layer=0, specific_flow=1.7
    )
    assert [link.capacity for link in override] == [3.4, 3.4]


@pytest.mark.parametrize("reverse", [False, True])
def test_two_stairs_use_source_speed_for_both_directions(reverse):
    net = Network(parameters=HydraulicParameters(stair_speed_coefficient=60))
    net.add_stair("a", area=20, riser=0.17, tread=0.30)
    net.add_stair("b", area=20, riser=0.19, tread=0.26)
    source, target = ("b", "a") if reverse else ("a", "b")
    links = net.connect(source, target, kind="stair", width=1, boundary_layer=0)
    expected = net.node(source).speed_constant / (4 * 0.266)
    assert [link.capacity for link in links] == [expected, expected]


@pytest.mark.parametrize("coefficient", [40, 60])
def test_stair_coefficient_reaches_reference_cost_and_movement(coefficient):
    parameters = HydraulicParameters(stair_speed_coefficient=coefficient)
    net = Network(parameters=parameters)
    net.add_stair("stair", area=100, riser=0.18, tread=0.28)
    net.add_safe("safe")
    net.connect("stair", "safe", width=10, kind="stair", length=10)
    speed = coefficient * math.sqrt(0.28 / 0.18) / 60 * (1 - 0.266 * 0.54)
    cost = routing_costs.edge_costs(
        net.nodes, net.links, "shortest_free_flow_time", parameters=parameters
    )
    assert cost == pytest.approx([10 / speed])
    sim = NetworkSimulation(net, [Population("stair", 1, speed=10)], dt=0.01)
    assert sim.run(seed=1).evacuation_time == pytest.approx(
        10 / speed, abs=0.02
    )


def test_networks_remain_independent_and_configuration_cannot_be_replaced():
    first = room_network(
        HydraulicParameters(level_speed_constant=1, door_specific_flow=2)
    )
    sim = NetworkSimulation(first, [Population("room", 5, speed=10)])
    before = sim.run(seed=1)
    second = room_network(
        HydraulicParameters(level_speed_constant=2, door_specific_flow=3)
    )
    NetworkSimulation(second, [Population("room", 5)]).run(seed=1)
    after = sim.run(seed=1)
    np.testing.assert_array_equal(before.exit_times, after.exit_times)
    assert first.node("room").speed_constant == 1
    assert second.node("room").speed_constant == 2
    assert first.links[0].capacity != second.links[0].capacity
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.parameters.min_density = 1
    with pytest.raises(AttributeError):
        first.parameters = second.parameters
    with pytest.raises(TypeError):
        NetworkSimulation(
            first, [Population("room", 1)], parameters=second.parameters
        )


def test_custom_jam_density_is_used_by_simulation_and_scenario_probe():
    net = room_network(HydraulicParameters(speed_density_slope=0.2))
    sim = NetworkSimulation(net, [Population("room", 1)], max_density=4.5)
    restored = Scenario.from_simulation(sim).simulation
    assert restored.max_density == 4.5
    with pytest.raises(ValueError, match="max_density"):
        NetworkSimulation(net, [Population("room", 1)], max_density=5)


def test_custom_peak_is_used_by_existing_supply_reduction_equation():
    net = room_network(
        HydraulicParameters(speed_density_slope=0.2, min_density=3)
    )
    sim = NetworkSimulation(net, [Population("room", 1)], max_density=4)
    run = _Run(sim, np.random.default_rng(1), False)
    allowance = run._allowance(np.array([3.5, 0]), np.array([10, 0]))
    assert allowance[0] == 5  # (4 - 3.5) / (4 - 3) * 10
    with pytest.warns(UserWarning, match="peak-flow"):
        NetworkSimulation(net, [Population("room", 1)], max_density=2.8)


def custom_scenario():
    net = room_network(
        HydraulicParameters(speed_density_slope=0.2, door_boundary_layer=0.2)
    )
    net.connect("room", "safe", width=1, specific_flow=2, boundary_layer=0)
    return Scenario.from_simulation(
        NetworkSimulation(net, [Population("room", 4)]), seed=17
    )


def test_schema_round_trip_preserves_inputs_configuration_and_results(tmp_path):
    original = custom_scenario()
    path = tmp_path / "custom.json"
    save_scenario(original, path)
    restored = load_scenario(path)
    assert restored.data == original.data
    a, b = original.simulation, restored.simulation
    assert a.network.parameters == b.network.parameters
    assert a.network.nodes == b.network.nodes
    assert a.network.links == b.network.links
    assert a.network._inputs == b.network._inputs
    np.testing.assert_array_equal(
        a.run(seed=17).exit_times, b.run(seed=17).exit_times
    )
    assert restored.data["connections"][-1]["boundary_layer"] == 0
    assert restored.data["connections"][-1]["specific_flow"] == 2


@pytest.mark.parametrize(
    "section,key", [("nodes", "speed_constant"), ("links", "capacity")]
)
def test_inconsistent_snapshot_is_rejected_and_never_used_as_override(
    section, key
):
    data = custom_scenario().to_dict()
    data["resolved_hydraulics"][section][0][key] *= 2
    with pytest.raises(
        ScenarioError, match=rf"resolved_hydraulics.{section}\[0\].{key}"
    ):
        scenario_from_dict(data)


def test_changed_inputs_require_removing_or_updating_snapshot():
    data = custom_scenario().to_dict()
    data["hydraulic_parameters"]["level_speed_constant"] = 2
    with pytest.raises(ScenarioError, match="snapshot"):
        scenario_from_dict(data)
    del data["resolved_hydraulics"]
    rebuilt = scenario_from_dict(data)
    assert rebuilt.simulation.network.node("room").speed_constant == 2


@pytest.mark.parametrize(
    "key,value", [("format_version", 999), ("hydraulic_model_version", "999")]
)
def test_schema_and_model_versions_are_checked_independently(key, value):
    data = custom_scenario().to_dict()
    data[key] = value
    with pytest.raises(ScenarioError, match=key):
        scenario_from_dict(data)


def test_schema_requires_complete_configuration():
    data = custom_scenario().to_dict()
    del data["hydraulic_parameters"]["min_density"]
    with pytest.raises(ScenarioError, match="min_density"):
        scenario_from_dict(data)


def test_legacy_defaults_do_not_follow_library_defaults(monkeypatch, tmp_path):
    legacy = {
        "format_version": 1,
        "nodes": [
            {"name": "room", "kind": "room", "area": 100},
            {"name": "safe", "kind": "safe"},
        ],
        "connections": [{"source": "room", "target": "safe", "width": 1}],
        "populations": [{"node": "room", "count": 1}],
    }
    original = copy.deepcopy(legacy)
    monkeypatch.setattr(
        hydraulic,
        "DEFAULT_HYDRAULIC_PARAMETERS",
        HydraulicParameters(level_speed_constant=2, door_specific_flow=3),
    )
    restored = scenario_from_dict(legacy)
    net = restored.simulation.network
    assert net.parameters == DEFAULT
    assert net.node("room").speed_constant == 84 / 60
    assert net.links[0].capacity == 1.3 * 0.7
    assert legacy == original
    path = tmp_path / "migrated.json"
    save_scenario(restored, path)
    data = load_scenario(path).data
    assert data["format_version"] == 2
    assert data["hydraulic_model_version"] == "1"
    assert data["hydraulic_parameters"] == dataclasses.asdict(DEFAULT)


def test_peak_flow_remains_representable_when_four_times_slope_overflows():
    parameters = HydraulicParameters(speed_density_slope=1e308, min_density=0)
    peak = parameters.peak_flow_density
    expected = peak * float(hydraulic.speed(peak, 2, parameters=parameters))
    assert expected > 0
    assert hydraulic.max_specific_flow(2, parameters=parameters) == expected


def test_scalar_too_large_for_float_is_rejected():
    with pytest.raises(ValueError, match="speed_density_slope.*finite"):
        HydraulicParameters(speed_density_slope=10**400)


@pytest.mark.parametrize("level_k,chosen", [(0.5, "a->stair"), (2, "a->level")])
def test_public_reference_routes_use_resolved_custom_node_speeds(
    level_k, chosen
):
    net = Network(
        parameters=HydraulicParameters(
            level_speed_constant=level_k, stair_speed_coefficient=60
        )
    )
    net.add_room("a", area=100)
    net.add_room("level", area=100)
    net.add_stair("stair", area=100, riser=0.18, tread=0.28)
    net.add_safe("safe")
    net.connect("a", "level", width=2, length=0, bidirectional=False)
    net.connect("a", "stair", width=2, length=0, bidirectional=False)
    net.connect("level", "safe", width=2, length=10)
    net.connect("stair", "safe", width=2, length=10, kind="stair")
    table = net.route_table(routing_policy="shortest_free_flow_time")
    assert net.links[table[0]].name == chosen
    assert tuple(
        net.links[i].name
        for i in net.route_choices(routing_policy="shortest_free_flow_time")[0]
    ) == (chosen,)
    assert len(net.route_choices()[0]) == 2


@pytest.mark.parametrize("flow,layer", [(1, 0), (2, 0.25), (3, 0.1)])
def test_configured_door_capacity_controls_existing_flow_allocation(
    flow, layer
):
    net = Network(
        parameters=HydraulicParameters(
            door_specific_flow=flow, door_boundary_layer=layer
        )
    )
    net.add_room("room", area=100)
    net.add_safe("safe")
    net.connect("room", "safe", width=1)
    sim = NetworkSimulation(net, [Population("room", 10)], dt=0.01)
    expected = 9 / (flow * (1 - 2 * layer))
    assert sim.run(seed=1).evacuation_time == pytest.approx(expected, abs=0.02)


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s["nodes"].pop(),
        lambda s: s["links"][0].pop("capacity"),
        lambda s: s["links"][0].update(index=True),
        lambda s: s["nodes"][1].update(area=100),
    ],
)
def test_snapshot_structure_and_non_numeric_fields_are_checked(change):
    data = custom_scenario().to_dict()
    change(data["resolved_hydraulics"])
    with pytest.raises(ScenarioError, match="resolved_hydraulics"):
        scenario_from_dict(data)


def test_snapshot_roundoff_tolerance_does_not_override_reconstruction():
    data = custom_scenario().to_dict()
    expected = data["resolved_hydraulics"]["links"][0]["capacity"]
    data["resolved_hydraulics"]["links"][0]["capacity"] *= 1 + 5e-13
    restored = scenario_from_dict(data)
    assert restored.simulation.network.links[0].capacity == expected


def test_unrecognized_historical_model_is_not_silently_reinterpreted(
    monkeypatch,
):
    data = custom_scenario().to_dict()
    data["format_version"] = 1
    for key in (
        "hydraulic_parameters",
        "hydraulic_model_version",
        "resolved_hydraulics",
    ):
        del data[key]
    monkeypatch.setattr(hydraulic, "HYDRAULIC_MODEL_VERSION", "unsupported")
    with pytest.raises(ScenarioError, match="hydraulic_model_version"):
        scenario_from_dict(data)


def test_lower_custom_jam_density_rejects_incompatible_simulation_default():
    net = room_network(HydraulicParameters(speed_density_slope=0.5))
    with pytest.raises(ValueError, match="max_density must be in"):
        NetworkSimulation(net, [Population("room", 1)])


def test_scenario_probe_does_not_impose_geometry_on_global_parameters():
    net = room_network(HydraulicParameters(door_boundary_layer=2))
    sim = NetworkSimulation(net, [Population("room", 1)])
    assert Scenario.from_simulation(sim).simulation.network.links == net.links


def test_numeric_snapshot_fields_accept_equivalent_integer_json_values():
    data = custom_scenario().to_dict()
    data["resolved_hydraulics"]["links"][-1]["capacity"] = 2
    data["connections"][-1]["specific_flow"] = 2.0
    assert scenario_from_dict(data).simulation.network.links[-1].capacity == 2
