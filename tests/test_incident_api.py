from datetime import datetime, timezone

from incident_api import __version__
from incident_api.client import parse_bool, parse_datetime_input, parse_monitors


def test_version():
    assert __version__ == "0.1.0"


def test_parse_bool_valid_values():
    assert parse_bool("true") is True
    assert parse_bool("1") is True
    assert parse_bool("yes") is True
    assert parse_bool("false") is False
    assert parse_bool("0") is False
    assert parse_bool("no") is False
    assert parse_bool(None) is None


def test_parse_monitors_parses_integers():
    assert parse_monitors("1,2,3") == [1, 2, 3]
    assert parse_monitors("  10 , 20 ") == [10, 20]
    assert parse_monitors(" ") is None
    assert parse_monitors(None) is None


def test_parse_datetime_input_offset_minutes():
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = parse_datetime_input("10m", now=base)
    assert result == "2026-01-01T12:10:00Z"


def test_parse_datetime_input_iso_string_with_z():
    result = parse_datetime_input("2026-03-08T10:00:00Z")
    # Expect normalized UTC with Z suffix
    assert result == "2026-03-08T10:00:00Z"

