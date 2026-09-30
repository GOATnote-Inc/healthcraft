"""Advertised encounter date bounds filter known arrival instants inclusively."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from healthcraft import temporal
from healthcraft.entities.base import EntityType
from healthcraft.entities.encounters import Encounter, ESILevel
from healthcraft.mcp.server import create_server
from healthcraft.world.state import WorldState

REPO_ROOT = Path(__file__).resolve().parents[2]
SEARCH_SCHEMA = next(
    tool["parameters"]
    for tool in json.loads((REPO_ROOT / "configs/mcp-tools.json").read_text())["tools"]
    if tool["name"] == "searchEncounters"
)
LOWER = "2026-01-15T00:00:00Z"
UPPER = "2026-01-16T00:00:00Z"


def _call(world, params, *, valid=True):
    if valid:
        jsonschema.validate(params, SEARCH_SCHEMA, format_checker=jsonschema.FormatChecker())
    return create_server(world).call_tool("searchEncounters", params)


def _ids(response):
    assert response["status"] == "ok", response
    return [entry["id"] for entry in response["data"]]


@pytest.fixture(params=["dataclass", "historical_dict"])
def world(request):
    world = WorldState()
    boundary = datetime(2026, 1, 15, tzinfo=timezone.utc)
    for index, offset in enumerate((-1, 0, 12, 24, 25), 1):
        encounter = Encounter(
            id=f"ENC-{index:08X}",
            entity_type=EntityType.ENCOUNTER,
            created_at=world.timestamp,
            updated_at=world.timestamp,
            patient_id="PAT-AAAAAAAA",
            chief_complaint="Synthetic complaint",
            esi_level=ESILevel.URGENT,
            disposition="discharged",
            arrival_time=boundary + timedelta(hours=offset),
        )
        if request.param == "historical_dict":
            record = asdict(encounter)
            record["arrival_time"] = encounter.arrival_time.isoformat()
        else:
            record = encounter
        world.put_entity("encounter", encounter.id, record)
    return world


def test_both_bounds_include_boundary_instants(world):
    result = _call(world, {"date_from": LOWER, "date_to": UPPER})
    assert _ids(result) == ["ENC-00000002", "ENC-00000003", "ENC-00000004"]


@pytest.mark.parametrize(
    ("bound", "value", "expected"),
    [
        ("date_from", LOWER, ["ENC-00000002", "ENC-00000003", "ENC-00000004", "ENC-00000005"]),
        ("date_to", UPPER, ["ENC-00000001", "ENC-00000002", "ENC-00000003", "ENC-00000004"]),
    ],
)
def test_optional_single_bound_is_applied(world, bound, value, expected):
    assert _ids(_call(world, {bound: value})) == expected


def test_equivalent_timezone_offsets_define_the_same_inclusive_window(world):
    result = _call(
        world,
        {
            "date_from": "2026-01-15T05:30:00+05:30",
            "date_to": "2026-01-14T21:00:00-03:00",
        },
    )
    assert _ids(result) == ["ENC-00000002"]


def test_stored_offset_instants_and_fractional_seconds_are_compared_correctly():
    world = WorldState()
    times = [
        "2026-01-14T21:00:00.123456-03:00",
        "2026-01-15T00:00:00.123455Z",
        "2026-01-15T00:00:00.123457+00:00",
    ]
    for index, arrival in enumerate(times, 1):
        world.put_entity("encounter", f"ENC-{index:08X}", {"arrival_time": arrival})
    result = _call(
        world,
        {
            "date_from": "2026-01-15T00:00:00.123456Z",
            "date_to": "2026-01-15T00:00:00.123456+00:00",
        },
    )
    assert _ids(result) == ["ENC-00000001"]
    assert result["data"][0]["arrival_time"] == times[0]


@pytest.mark.parametrize("bound", ["date_from", "date_to"])
@pytest.mark.parametrize(
    "invalid",
    [
        "",
        None,
        0,
        [],
        {},
        "not-a-date",
        "2026-01-15",
        "2026-01-15T00:00:00",
        "2026-01-15 00:00:00Z",
        "2026-01-15T00:00Z",
        "2026-01-15T00:00:00+0000",
        "2026-02-30T00:00:00Z",
        "2026-01-15T00:00:00+05:60",
    ],
)
def test_invalid_bounds_return_audited_errors_even_without_encounters(bound, invalid):
    world = WorldState()
    result = _call(world, {bound: invalid}, valid=False)
    assert result["status"] == "error", result
    assert result["code"] == "invalid_params"
    assert bound in result["message"]
    assert world.audit_log[-1].error_code == "invalid_params"


def test_reversed_bounds_are_rejected_by_instant_order(world):
    result = _call(
        world,
        {
            "date_from": "2026-01-15T00:00:01Z",
            "date_to": "2026-01-15T01:00:00+01:00",
        },
    )
    assert result["status"] == "error", result
    assert result["code"] == "invalid_params"


@pytest.mark.parametrize(
    "arrival", [None, "", "bad", "2026-01-15", "2026-01-15T12:00:00", datetime(2026, 1, 15), 42]
)
def test_unknown_or_invalid_arrival_is_excluded_only_from_bounded_search(arrival):
    world = WorldState()
    world.put_entity("encounter", "ENC-00000001", {"arrival_time": arrival})
    world.put_entity("encounter", "ENC-00000002", {})

    assert _ids(_call(world, {"date_from": LOWER, "date_to": UPPER})) == []
    assert _ids(_call(world, {})) == ["ENC-00000001", "ENC-00000002"]


def test_existing_filters_combine_with_dates_before_applying_limit(world):
    world.put_entity(
        "encounter",
        "ENC-AAAAAAAA",
        {
            "patient_id": "PAT-BBBBBBBB",
            "arrival_time": LOWER,
            "chief_complaint": "Other complaint",
            "esi_level": 4,
            "disposition": "admitted",
        },
    )
    result = _call(
        world,
        {
            "patient_id": "PAT-AAAAAAAA",
            "chief_complaint": "synthetic",
            "esi_level": 3,
            "disposition": "discharged",
            "date_from": LOWER,
            "date_to": UPPER,
            "limit": 2,
        },
    )
    assert _ids(result) == ["ENC-00000002", "ENC-00000003"]
    assert _ids(_call(world, {"date_from": LOWER, "chief_complaint": "other"})) == ["ENC-AAAAAAAA"]


def test_default_pagination_and_no_has_more_signal_are_unchanged():
    world = WorldState()
    for index in range(15):
        world.put_entity("encounter", f"ENC-{index:08X}", {"arrival_time": LOWER})
    for params in ({}, {"limit": 50}, {"date_from": LOWER, "date_to": UPPER}):
        result = _call(world, params)
        assert len(_ids(result)) == 10
        assert "hasMore" not in result
        assert "has_more" not in result


def test_fractional_precision_beyond_microseconds_is_not_silently_discarded():
    world = WorldState()
    for index, fraction in enumerate(("1234560", "1234561", "1234562", "12345610"), 1):
        world.put_entity(
            "encounter",
            f"ENC-{index:08X}",
            {"arrival_time": f"2026-01-15T00:00:00.{fraction}Z"},
        )
    result = _call(
        world,
        {
            "date_from": "2026-01-15T00:00:00.1234561Z",
            "date_to": "2026-01-15T00:00:00.1234561Z",
        },
    )
    assert _ids(result) == ["ENC-00000002", "ENC-00000004"]


def test_positive_submicrosecond_arrival_is_after_zero_fraction_upper_bound():
    world = WorldState()
    world.put_entity("encounter", "ENC-00000001", {"arrival_time": "2026-01-15T00:00:00.0000001Z"})
    assert _ids(_call(world, {"date_to": "2026-01-15T00:00:00.0000000Z"})) == []


def test_reversed_submicrosecond_bounds_are_rejected():
    result = _call(
        WorldState(),
        {
            "date_from": "2026-01-15T00:00:00.0000001Z",
            "date_to": "2026-01-15T00:00:00.0000000Z",
        },
    )
    assert result["status"] == "error", result
    assert result["code"] == "invalid_params"


@pytest.mark.parametrize(
    "fraction", ["1", "12", "123", "1234", "12345", "123456", "1234567", "0000001"]
)
def test_fractional_windows_work_with_python310_parser_constraints(monkeypatch, fraction):
    class Python310Datetime(datetime):
        @classmethod
        def fromisoformat(cls, value):
            # Python 3.10 permits only three or six fractional digits. Emulate
            # that boundary while executing the real date validation/parser.
            match = re.search(r"\.([0-9]+)", value)
            if match and len(match.group(1)) not in (3, 6):
                raise ValueError("Invalid isoformat string")
            return super().fromisoformat(value)

    monkeypatch.setattr(temporal, "datetime", Python310Datetime)
    world = WorldState()
    world.put_entity(
        "encounter",
        "ENC-00000001",
        {"arrival_time": f"2026-01-14T21:00:00.{fraction}-03:00"},
    )
    world.put_entity(
        "encounter",
        "ENC-00000002",
        {"arrival_time": f"2026-01-15T00:00:00.{fraction}1Z"},
    )
    result = _call(
        world,
        {
            "date_from": f"2026-01-15T00:00:00.{fraction}Z",
            "date_to": f"2026-01-15T00:00:00.{fraction}Z",
        },
    )
    assert _ids(result) == ["ENC-00000001"]
