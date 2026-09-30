"""Source times retain precision and uncertainty without inferred calendar anchors."""

from datetime import date, datetime, timezone

import pytest

from healthcraft.temporal import instant_key, resolve_source_time


@pytest.mark.parametrize(
    "value,status",
    [
        (None, "missing"),
        ("2026", "date_only"),
        ("2026-01", "date_only"),
        ("2026-01-15", "date_only"),
        (date(2026, 1, 15), "date_only"),
        ("08:35", "time_only"),
        ("08:35:00+01:00", "time_only"),
        ("2026-01-15T08:35:00", "naive"),
        (datetime(2026, 1, 15, 8, 35), "naive"),
        ("pending", "unresolved"),
        ("30 minutes later", "unresolved"),
        ("2026-02-30T08:35:00Z", "invalid"),
        (True, "invalid"),
        (123, "invalid"),
        ("2016-12-31T23:59:60Z", "unsupported"),
    ],
)
def test_unresolved_source_is_not_completed_with_other_clocks(value, status):
    timestamp, actual, keys = resolve_source_time({"time": value})
    assert timestamp is None and actual == status and keys == ("time",)


@pytest.mark.parametrize(
    "value",
    [
        "2026-01-15T08:35:00Z",
        "2026-01-15t08:35:00z",
        "2026-01-15T09:35:00.123456789+01:00",
        datetime(2026, 1, 15, 8, 35, tzinfo=timezone.utc),
    ],
)
def test_explicit_authored_instants_keep_original_representation(value):
    assert resolve_source_time({"time": value}) == (value, "explicit", ("time",))


def test_exact_fraction_order_and_equivalent_zones():
    assert instant_key("2026-01-15T08:00:00.1234567Z") < instant_key("2026-01-15T08:00:00.1234568Z")
    assert instant_key("2026-01-15T08:00:00.12345670Z") == instant_key(
        "2026-01-15T09:00:00.1234567+01:00"
    )
    first = "2026-01-15T08:00:00Z"
    assert resolve_source_time({"time": first, "timestamp": "2026-01-15T09:00:00+01:00"}) == (
        first,
        "explicit",
        ("time", "timestamp"),
    )


@pytest.mark.parametrize("other", ["2026-01-15T08:01:00Z", "08:00", None, "invalid"])
def test_competing_timing_fields_do_not_silently_choose_one(other):
    assert resolve_source_time({"time": "2026-01-15T08:00:00Z", "timestamp": other}) == (
        None,
        "conflicting",
        ("time", "timestamp"),
    )


def test_availability_and_update_timestamps_are_not_observation_time():
    assert resolve_source_time(
        {"issued": "2026-01-15T08:00:00Z", "updated_at": "2026-01-15T09:00:00Z"}
    ) == (None, "missing", ())


@pytest.mark.parametrize(
    "value,status",
    [
        ("08:35:00.123456789+01:00", "time_only"),
        ("2026-01-15T08:35:00.123456789", "naive"),
    ],
)
def test_partial_time_precision_has_the_same_status_on_supported_python_versions(value, status):
    assert resolve_source_time({"time": value}) == (None, status, ("time",))
