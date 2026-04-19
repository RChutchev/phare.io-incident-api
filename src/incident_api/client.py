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
    """Return UTC datetime as Phare expects, e.g. 2023-11-07T05:31:56Z (no fractional seconds).

    The API validates incident_at / recovery_at / published_at like published_at in their docs.
    Use Z suffix, not +00:00 — +00:00 was rejected with Y-m-d\\TH:i:sp validation errors.
    """
    dt_utc = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


# Phare API allows incident_at/recovery_at at most 9 minutes in the future.
MAX_FUTURE_MINUTES = 9


def parse_datetime_input(
    value: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """
    Parse a datetime input which can be:

    - An ISO 8601 datetime (e.g. 2026-03-08T12:00:00+00:00)
    - A relative offset: '10s', '10m', '1h', '1d' (after now) or '-10m', '-1h', '-1d' (before now)

    Future times are capped to now + 9 minutes to comply with Phare API rules.
    Returns an ISO 8601 string in UTC with Z suffix (e.g. 2023-11-07T05:31:56Z), or None.
    """
    if value is None:
        return None

    text = value.strip()
    if not text:
        return None

    # Relative offsets: optional leading minus, then <integer><unit>, unit in {s, m, h, d}
    if text[-1] in {"s", "m", "h", "d"}:
        rest = text[:-1]
        negative = rest.startswith("-")
        if negative:
            rest = rest[1:]
        if rest.isdigit():
            amount = int(rest)
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

            if negative:
                dt = now - delta
            else:
                dt = now + delta
                # Phare allows at most 9 minutes in the future; cap to comply
                max_future = now + timedelta(minutes=MAX_FUTURE_MINUTES)
                if dt > max_future:
                    dt = max_future

            return _format_datetime(dt)

    # Absolute datetime string
    try:
        normalized = text
        if text.endswith("Z"):
            normalized = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # Cap absolute future times to now + 9 minutes
        if now is None:
            now = datetime.now(timezone.utc)
        max_future = now + timedelta(minutes=MAX_FUTURE_MINUTES)
        if dt > max_future:
            dt = max_future
        return _format_datetime(dt)
    except ValueError as exc:
        raise ValueError(
            "Invalid datetime value "
            f"'{value}'. Use ISO 8601 (e.g. 2026-03-08T12:00:00Z) "
            "or a relative offset like '10m', '1h', '-10m', '-1d'."
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


# --- Incident updates (sub-resource under /uptime/incidents/{id}/updates) ---

INCIDENT_UPDATE_STATE_VALUES = {
    "unknown",
    "investigating",
    "identified",
    "monitoring",
    "resolved",
}


def _headers_with_auth(
    token: Optional[str],
    project_id: Optional[str],
    project_slug: Optional[str],
    *,
    json_body: bool = False,
) -> Dict[str, str]:
    if not token:
        raise IncidentApiError(
            "Missing Phare.io token. Provide it via the PHARE_TOKEN environment variable."
        )
    headers: Dict[str, str] = {"Authorization": f"Bearer {token}"}
    if json_body:
        headers["Content-Type"] = "application/json"
    if project_id:
        headers["X-Phare-Project-Id"] = str(project_id)
    if project_slug:
        headers["X-Phare-Project-Slug"] = project_slug
    return headers


def list_incident_updates(
    *,
    token: Optional[str],
    project_id: Optional[str],
    project_slug: Optional[str],
    incident_id: int,
    page: int = 1,
    per_page: int = 20,
    timeout: int = 10,
) -> Dict[str, Any]:
    """GET /uptime/incidents/{incidentId}/updates"""
    if incident_id <= 0:
        raise IncidentApiError("incident_id must be a positive integer.")

    headers = _headers_with_auth(token, project_id, project_slug)
    url = f"{PHARE_API_BASE_URL}/uptime/incidents/{incident_id}/updates"
    params = {"page": page, "per_page": per_page}
    response = requests.get(url, headers=headers, params=params, timeout=timeout)
    if response.status_code != 200:
        message = f"Failed to list incident updates (status {response.status_code})."
        try:
            data = response.json()
            error_text = json.dumps(data, indent=2)
        except ValueError:
            error_text = response.text
        raise IncidentApiError(f"{message}\nResponse body:\n{error_text}")
    return response.json()


def get_incident_update(
    *,
    token: Optional[str],
    project_id: Optional[str],
    project_slug: Optional[str],
    incident_id: int,
    incident_update_id: int,
    timeout: int = 10,
) -> Dict[str, Any]:
    """GET /uptime/incidents/{incidentId}/updates/{incidentUpdateId}"""
    if incident_id <= 0 or incident_update_id <= 0:
        raise IncidentApiError(
            "incident_id and incident_update_id must be positive integers."
        )

    headers = _headers_with_auth(token, project_id, project_slug)
    url = (
        f"{PHARE_API_BASE_URL}/uptime/incidents/{incident_id}/updates/"
        f"{incident_update_id}"
    )
    response = requests.get(url, headers=headers, timeout=timeout)
    if response.status_code != 200:
        message = f"Failed to get incident update (status {response.status_code})."
        try:
            data = response.json()
            error_text = json.dumps(data, indent=2)
        except ValueError:
            error_text = response.text
        raise IncidentApiError(f"{message}\nResponse body:\n{error_text}")
    return response.json()


def create_incident_update(
    *,
    token: Optional[str],
    project_id: Optional[str],
    project_slug: Optional[str],
    incident_id: int,
    state: str,
    content: str,
    published_at: Optional[str] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """POST /uptime/incidents/{incidentId}/updates"""
    if incident_id <= 0:
        raise IncidentApiError("incident_id must be a positive integer.")
    if state not in INCIDENT_UPDATE_STATE_VALUES:
        allowed = ", ".join(sorted(INCIDENT_UPDATE_STATE_VALUES))
        raise IncidentApiError(f"Invalid update state '{state}'. Allowed: {allowed}.")

    body: Dict[str, Any] = {"state": state, "content": content}
    if published_at is not None:
        body["published_at"] = published_at

    headers = _headers_with_auth(token, project_id, project_slug, json_body=True)
    url = f"{PHARE_API_BASE_URL}/uptime/incidents/{incident_id}/updates"
    response = requests.post(url, headers=headers, json=body, timeout=timeout)
    if response.status_code != 201:
        message = f"Failed to create incident update (status {response.status_code})."
        try:
            data = response.json()
            error_text = json.dumps(data, indent=2)
        except ValueError:
            error_text = response.text
        raise IncidentApiError(f"{message}\nResponse body:\n{error_text}")
    return response.json()


def update_incident_update(
    *,
    token: Optional[str],
    project_id: Optional[str],
    project_slug: Optional[str],
    incident_id: int,
    incident_update_id: int,
    state: Optional[str] = None,
    content: Optional[str] = None,
    published_at: Optional[str] = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """POST /uptime/incidents/{incidentId}/updates/{incidentUpdateId}"""
    if incident_id <= 0 or incident_update_id <= 0:
        raise IncidentApiError(
            "incident_id and incident_update_id must be positive integers."
        )
    if state is not None and state not in INCIDENT_UPDATE_STATE_VALUES:
        allowed = ", ".join(sorted(INCIDENT_UPDATE_STATE_VALUES))
        raise IncidentApiError(f"Invalid update state '{state}'. Allowed: {allowed}.")

    payload: Dict[str, Any] = {
        "state": state,
        "content": content,
        "published_at": published_at,
    }
    body = {k: v for k, v in payload.items() if v is not None}
    if not body:
        raise IncidentApiError(
            "At least one of state, content, or published_at must be set."
        )

    headers = _headers_with_auth(token, project_id, project_slug, json_body=True)
    url = (
        f"{PHARE_API_BASE_URL}/uptime/incidents/{incident_id}/updates/"
        f"{incident_update_id}"
    )
    response = requests.post(url, headers=headers, json=body, timeout=timeout)
    if response.status_code != 200:
        message = f"Failed to update incident update (status {response.status_code})."
        try:
            data = response.json()
            error_text = json.dumps(data, indent=2)
        except ValueError:
            error_text = response.text
        raise IncidentApiError(f"{message}\nResponse body:\n{error_text}")
    return response.json()


def delete_incident_update(
    *,
    token: Optional[str],
    project_id: Optional[str],
    project_slug: Optional[str],
    incident_id: int,
    incident_update_id: int,
    timeout: int = 10,
) -> None:
    """DELETE /uptime/incidents/{incidentId}/updates/{incidentUpdateId}"""
    if incident_id <= 0 or incident_update_id <= 0:
        raise IncidentApiError(
            "incident_id and incident_update_id must be positive integers."
        )

    headers = _headers_with_auth(token, project_id, project_slug)
    url = (
        f"{PHARE_API_BASE_URL}/uptime/incidents/{incident_id}/updates/"
        f"{incident_update_id}"
    )
    response = requests.delete(url, headers=headers, timeout=timeout)
    if response.status_code != 204:
        message = f"Failed to delete incident update (status {response.status_code})."
        try:
            data = response.json()
            error_text = json.dumps(data, indent=2)
        except ValueError:
            error_text = response.text
        raise IncidentApiError(f"{message}\nResponse body:\n{error_text}")
