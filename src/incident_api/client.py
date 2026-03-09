import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests

PHARE_API_BASE_URL = os.getenv("PHARE_API_BASE_URL", "https://api.phare.io")

IMPACT_VALUES = {
    "unknown",
    "operational",
    "degraded_performance",
    "partial_outage",
    "major_outage",
    "maintenance",
}


class IncidentApiError(RuntimeError):
    """Raised when the Phare.io API returns an error response."""


def parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise ValueError(
        f"Invalid boolean value '{value}'. "
        "Use one of: true, false, 1, 0, yes, no."
    )


def parse_monitors(value: Optional[str]) -> Optional[List[int]]:
    if value is None or not value.strip():
        return None
    parts: Iterable[str] = (p.strip() for p in value.split(","))
    monitors: List[int] = []
    for part in parts:
        if not part:
            continue
        try:
            monitors.append(int(part))
        except ValueError as exc:
            raise ValueError(
                f"Invalid monitor id '{part}'. Expected an integer."
            ) from exc
    return monitors or None


def _format_datetime(dt: datetime) -> str:
    """Return an RFC 3339 / ISO 8601 string in UTC with Z suffix."""
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.isoformat().replace("+00:00", "Z")


def parse_datetime_input(
    value: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """
    Parse a datetime input which can be:

    - An ISO 8601 datetime (e.g. 2026-03-08T12:00:00Z)
    - A relative offset like '10s', '10m', '1h', '10h', '1d'

    Returns an ISO 8601 string in UTC with Z suffix, or None.
    """
    if value is None:
        return None

    text = value.strip()
    if not text:
        return None

    # Relative offsets: <integer><unit>, where unit in {s, m, h, d}
    if text[-1] in {"s", "m", "h", "d"} and text[:-1].isdigit():
        amount = int(text[:-1])
        unit = text[-1]

        if now is None:
            now = datetime.now(timezone.utc)

        if unit == "s":
            delta = timedelta(seconds=amount)
        elif unit == "m":
            delta = timedelta(minutes=amount)
        elif unit == "h":
            delta = timedelta(hours=amount)
        else:  # unit == "d"
            delta = timedelta(days=amount)

        return _format_datetime(now + delta)

    # Absolute datetime string
    try:
        normalized = text
        if text.endswith("Z"):
            # Python's fromisoformat does not understand 'Z'
            normalized = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            # Assume UTC if no timezone is provided
            dt = dt.replace(tzinfo=timezone.utc)
        return _format_datetime(dt)
    except ValueError as exc:
        raise ValueError(
            "Invalid datetime value "
            f"'{value}'. Use ISO 8601 (e.g. 2026-03-08T12:00:00Z) "
            "or a relative offset like '10s', '10m', '1h', '1d'."
        ) from exc


def create_incident(
    *,
    token: Optional[str],
    project_id: Optional[str],
    project_slug: Optional[str],
    impact: Optional[str],
    title: Optional[str],
    description: Optional[str],
    exclude_from_downtime: Optional[bool],
    incident_at: Optional[str],
    recovery_at: Optional[str],
    monitors: Optional[List[int]],
    timeout: int = 10,
) -> Dict[str, Any]:
    if not token:
        raise IncidentApiError(
            "Missing Phare.io token. Provide it via the PHARE_TOKEN environment variable."
        )

    # Provide safe defaults for maintenance-style incidents when
    # title/description are not explicitly set.
    effective_title = title or "Maintenance window"
    effective_description = (
        description
        or "Automatic maintenance incident created by CI/CD pipeline."
    )

    payload: Dict[str, Any] = {
        "impact": impact or "maintenance",
        "title": effective_title,
        "description": effective_description,
        "exclude_from_downtime": exclude_from_downtime,
        "incident_at": incident_at,
        "recovery_at": recovery_at,
        "monitors": monitors,
    }

    if payload["impact"] not in IMPACT_VALUES:
        allowed = ", ".join(sorted(IMPACT_VALUES))
        raise IncidentApiError(
            f"Invalid impact '{payload['impact']}'. "
            f"Allowed values: {allowed}."
        )

    # Remove fields that are None so we only send what is set
    body = {k: v for k, v in payload.items() if v is not None}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    if project_id:
        headers["X-Phare-Project-Id"] = str(project_id)
    if project_slug:
        headers["X-Phare-Project-Slug"] = project_slug

    url = f"{PHARE_API_BASE_URL}/uptime/incidents"

    response = requests.post(url, headers=headers, json=body, timeout=timeout)

    if response.status_code not in {200, 201}:
        message = f"Failed to create incident (status {response.status_code})."
        try:
            data = response.json()
            error_text = json.dumps(data, indent=2)
        except ValueError:
            error_text = response.text
        raise IncidentApiError(f"{message}\nResponse body:\n{error_text}")

    return response.json()


def update_incident(
    *,
    token: Optional[str],
    project_id: Optional[str],
    project_slug: Optional[str],
    incident_id: int,
    impact: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    exclude_from_downtime: Optional[bool] = None,
    incident_at: Optional[str] = None,
    recovery_at: Optional[str] = None,
    monitors: Optional[List[int]] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    Update an existing incident using POST /uptime/incidents/{incidentId}.

    Only fields that are not None are sent in the request body, so you can
    update a subset of fields without affecting the others.
    """
    if not token:
        raise IncidentApiError(
            "Missing Phare.io token. Provide it via the PHARE_TOKEN environment variable."
        )

    if incident_id <= 0:
        raise IncidentApiError("incident_id must be a positive integer.")

    payload: Dict[str, Any] = {
        "impact": impact,
        "title": title,
        "description": description,
        "exclude_from_downtime": exclude_from_downtime,
        "incident_at": incident_at,
        "recovery_at": recovery_at,
        "monitors": monitors,
    }

    # Validate impact only if it is explicitly provided
    if impact is not None and impact not in IMPACT_VALUES:
        allowed = ", ".join(sorted(IMPACT_VALUES))
        raise IncidentApiError(
            f"Invalid impact '{impact}'. Allowed values: {allowed}."
        )

    body = {k: v for k, v in payload.items() if v is not None}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    if project_id:
        headers["X-Phare-Project-Id"] = str(project_id)
    if project_slug:
        headers["X-Phare-Project-Slug"] = project_slug

    url = f"{PHARE_API_BASE_URL}/uptime/incidents/{incident_id}"

    response = requests.post(url, headers=headers, json=body, timeout=timeout)

    if response.status_code != 200:
        message = f"Failed to update incident {incident_id} (status {response.status_code})."
        try:
            data = response.json()
            error_text = json.dumps(data, indent=2)
        except ValueError:
            error_text = response.text
        raise IncidentApiError(f"{message}\nResponse body:\n{error_text}")

    return response.json()


def recover_incident(
    *,
    token: Optional[str],
    project_id: Optional[str],
    project_slug: Optional[str],
    incident_id: int,
    timeout: int = 10,
) -> None:
    """
    Recover an incident using POST /uptime/incidents/{incidentId}/recover.
    """
    if not token:
        raise IncidentApiError(
            "Missing Phare.io token. Provide it via the PHARE_TOKEN environment variable."
        )

    if incident_id <= 0:
        raise IncidentApiError("incident_id must be a positive integer.")

    headers = {
        "Authorization": f"Bearer {token}",
    }

    if project_id:
        headers["X-Phare-Project-Id"] = str(project_id)
    if project_slug:
        headers["X-Phare-Project-Slug"] = project_slug

    url = f"{PHARE_API_BASE_URL}/uptime/incidents/{incident_id}/recover"

    response = requests.post(url, headers=headers, timeout=timeout)

    if response.status_code != 204:
        message = (
            f"Failed to recover incident {incident_id} "
            f"(status {response.status_code})."
        )
        try:
            data = response.json()
            error_text = json.dumps(data, indent=2)
        except ValueError:
            error_text = response.text
        raise IncidentApiError(f"{message}\nResponse body:\n{error_text}")


def delete_incident(
    *,
    token: Optional[str],
    project_id: Optional[str],
    project_slug: Optional[str],
    incident_id: int,
    timeout: int = 10,
) -> None:
    """
    Delete an incident using DELETE /uptime/incidents/{incidentId}.
    """
    if not token:
        raise IncidentApiError(
            "Missing Phare.io token. Provide it via the PHARE_TOKEN environment variable."
        )

    if incident_id <= 0:
        raise IncidentApiError("incident_id must be a positive integer.")

    headers = {
        "Authorization": f"Bearer {token}",
    }

    if project_id:
        headers["X-Phare-Project-Id"] = str(project_id)
    if project_slug:
        headers["X-Phare-Project-Slug"] = project_slug

    url = f"{PHARE_API_BASE_URL}/uptime/incidents/{incident_id}"

    response = requests.delete(url, headers=headers, timeout=timeout)

    if response.status_code != 204:
        message = (
            f"Failed to delete incident {incident_id} "
            f"(status {response.status_code})."
        )
        try:
            data = response.json()
            error_text = json.dumps(data, indent=2)
        except ValueError:
            error_text = response.text
        raise IncidentApiError(f"{message}\nResponse body:\n{error_text}")
