from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from incident_api import __version__
from incident_api.client import (
    IncidentApiError,
    _format_datetime,
    create_incident,
    delete_incident,
    parse_bool,
    parse_datetime_input,
    parse_monitors,
    recover_incident,
    update_incident,
)


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


def test_parse_bool_invalid_raises():
    with pytest.raises(ValueError, match="Invalid boolean"):
        parse_bool("maybe")


def test_parse_monitors_parses_integers():
    assert parse_monitors("1,2,3") == [1, 2, 3]
    assert parse_monitors("  10 , 20 ") == [10, 20]
    assert parse_monitors(" ") is None
    assert parse_monitors(None) is None


def test_parse_monitors_invalid_raises():
    with pytest.raises(ValueError, match="Invalid monitor id"):
        parse_monitors("1,abc,3")


def test_parse_datetime_input_offset_minutes():
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = parse_datetime_input("10m", now=base)
    # 10m in future is capped to 9 min by Phare API rule
    assert result == "2026-01-01T12:09:00Z"


def test_parse_datetime_input_iso_string_with_z():
    result = parse_datetime_input("2026-03-08T10:00:00Z")
    assert result == "2026-03-08T10:00:00Z"


def test_parse_datetime_input_offset_seconds():
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_datetime_input("30s", now=base) == "2026-01-01T12:00:30Z"


def test_parse_datetime_input_negative_offset():
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert parse_datetime_input("-10m", now=base) == "2026-01-01T11:50:00Z"
    assert parse_datetime_input("-1h", now=base) == "2026-01-01T11:00:00Z"


def test_parse_datetime_input_future_capped_at_9_minutes():
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # 1h in future should be capped to now + 9 min
    result = parse_datetime_input("1h", now=base)
    assert result == "2026-01-01T12:09:00Z"


def test_format_datetime_strips_microseconds_for_phare():
    """Phare expects UTC datetimes like published_at: 2023-11-07T05:31:56Z."""
    dt = datetime(2026, 1, 1, 12, 1, 2, 123456, tzinfo=timezone.utc)
    assert _format_datetime(dt) == "2026-01-01T12:01:02Z"


# --- API actions (mocked requests) ---


@patch("incident_api.client.requests.post")
def test_create_incident_success(mock_post):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {"id": 42, "slug": "INC-42"}

    result = create_incident(
        token="secret",
        project_id=None,
        project_slug=None,
        impact="maintenance",
        title="Test",
        description="Desc",
        exclude_from_downtime=None,
        incident_at=None,
        recovery_at=None,
        monitors=None,
    )

    assert result == {"id": 42, "slug": "INC-42"}
    mock_post.assert_called_once()
    call_kw = mock_post.call_args[1]
    assert call_kw["json"]["title"] == "Test"
    assert call_kw["json"]["impact"] == "maintenance"
    assert call_kw["headers"]["Authorization"] == "Bearer secret"
    assert call_kw["timeout"] == 10


@patch("incident_api.client.requests.post")
def test_create_incident_uses_defaults_when_title_description_empty(mock_post):
    mock_post.return_value.status_code = 201
    mock_post.return_value.json.return_value = {"id": 1}

    create_incident(
        token="x",
        project_id=None,
        project_slug=None,
        impact=None,
        title=None,
        description=None,
        exclude_from_downtime=None,
        incident_at=None,
        recovery_at=None,
        monitors=None,
    )

    call_kw = mock_post.call_args[1]
    assert call_kw["json"]["title"] == "Maintenance window"
    assert "CI/CD pipeline" in call_kw["json"]["description"]
    assert call_kw["json"]["impact"] == "maintenance"


def test_create_incident_raises_without_token():
    with pytest.raises(IncidentApiError, match="Missing Phare.io token"):
        create_incident(
            token=None,
            project_id=None,
            project_slug=None,
            impact="maintenance",
            title="T",
            description="D",
            exclude_from_downtime=None,
            incident_at=None,
            recovery_at=None,
            monitors=None,
        )


@patch("incident_api.client.requests.post")
def test_create_incident_raises_on_api_error(mock_post):
    mock_post.return_value.status_code = 422
    mock_post.return_value.json.return_value = {"message": "Validation failed"}
    mock_post.return_value.text = ""

    with pytest.raises(IncidentApiError, match="422"):
        create_incident(
            token="x",
            project_id=None,
            project_slug=None,
            impact="maintenance",
            title="T",
            description="D",
            exclude_from_downtime=None,
            incident_at=None,
            recovery_at=None,
            monitors=None,
        )


@patch("incident_api.client.requests.post")
def test_update_incident_success(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"id": 10, "title": "Updated"}

    result = update_incident(
        token="secret",
        project_id="1",
        project_slug=None,
        incident_id=10,
        title="Updated",
    )

    assert result["id"] == 10
    mock_post.assert_called_once()
    call = mock_post.call_args
    assert "/uptime/incidents/10" in call[0][0]
    assert call[1]["json"] == {"title": "Updated"}
    assert call[1]["headers"]["X-Phare-Project-Id"] == "1"


def test_update_incident_raises_invalid_id():
    with pytest.raises(IncidentApiError, match="positive integer"):
        update_incident(
            token="x",
            project_id=None,
            project_slug=None,
            incident_id=0,
        )


@patch("incident_api.client.requests.post")
def test_recover_incident_success(mock_post):
    mock_post.return_value.status_code = 204
    mock_post.return_value.json.side_effect = ValueError("no body")

    recover_incident(
        token="secret",
        project_id=None,
        project_slug="my-project",
        incident_id=5,
    )

    mock_post.assert_called_once()
    call = mock_post.call_args
    assert call[0][0].endswith("/uptime/incidents/5/recover")
    assert call[1]["headers"]["Authorization"] == "Bearer secret"
    assert call[1]["headers"]["X-Phare-Project-Slug"] == "my-project"


@patch("incident_api.client.requests.post")
def test_recover_incident_raises_on_error(mock_post):
    mock_post.return_value.status_code = 403
    mock_post.return_value.json.return_value = {"message": "Forbidden"}

    with pytest.raises(IncidentApiError, match="403"):
        recover_incident(
            token="x",
            project_id=None,
            project_slug=None,
            incident_id=1,
        )


@patch("incident_api.client.requests.delete")
def test_delete_incident_success(mock_delete):
    mock_delete.return_value.status_code = 204

    delete_incident(
        token="secret",
        project_id=99,
        project_slug=None,
        incident_id=7,
    )

    mock_delete.assert_called_once()
    call = mock_delete.call_args
    assert call[0][0].endswith("/uptime/incidents/7")
    assert call[1]["headers"]["X-Phare-Project-Id"] == "99"


@patch("incident_api.client.requests.delete")
def test_delete_incident_raises_on_error(mock_delete):
    mock_delete.return_value.status_code = 404
    mock_delete.return_value.json.return_value = {"message": "Not found"}

    with pytest.raises(IncidentApiError, match="404"):
        delete_incident(
            token="x",
            project_id=None,
            project_slug=None,
            incident_id=1,
        )

