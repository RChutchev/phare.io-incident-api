import json
import os
import sys
from typing import Optional

from .client import (
    IncidentApiError,
    create_incident,
    create_incident_update,
    delete_incident,
    delete_incident_update,
    get_incident_update,
    list_incident_updates,
    parse_bool,
    parse_datetime_input,
    parse_monitors,
    recover_incident,
    update_incident,
    update_incident_update,
)


def _get_env(name: str) -> Optional[str]:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _parse_int_env(name: str, default: int) -> int:
    raw = _get_env(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Invalid integer for {name}: {raw!r}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    operation = (_get_env("PHARE_OPERATION") or "create").lower()

    token = _get_env("PHARE_TOKEN")
    project_id = _get_env("PHARE_PROJECT_ID")
    project_slug = _get_env("PHARE_PROJECT_SLUG")
    impact = _get_env("PHARE_IMPACT")
    title = _get_env("PHARE_TITLE")
    description = _get_env("PHARE_DESCRIPTION")
    exclude_from_downtime_raw = _get_env("PHARE_EXCLUDE_FROM_DOWNTIME")
    monitors_raw = _get_env("PHARE_MONITORS")
    incident_at_raw = _get_env("PHARE_INCIDENT_AT")
    recovery_at_raw = _get_env("PHARE_RECOVERY_AT")
    incident_id_raw = _get_env("PHARE_INCIDENT_ID")
    incident_update_id_raw = _get_env("PHARE_INCIDENT_UPDATE_ID")
    update_state = _get_env("PHARE_UPDATE_STATE")
    update_content = _get_env("PHARE_UPDATE_CONTENT")
    update_published_at_raw = _get_env("PHARE_UPDATE_PUBLISHED_AT")

    try:
        exclude_from_downtime = (
            parse_bool(exclude_from_downtime_raw)
            if exclude_from_downtime_raw is not None
            else None
        )
        monitors = parse_monitors(monitors_raw)
        incident_at = parse_datetime_input(incident_at_raw)
        recovery_at = parse_datetime_input(recovery_at_raw)
        update_published_at = parse_datetime_input(update_published_at_raw)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    artifact_path = _get_env("PHARE_INCIDENT_ARTIFACT_PATH") or "phare-incident.json"

    github_output = os.getenv("GITHUB_OUTPUT")

    # --- Incident updates (sub-resource) ---
    if operation in {
        "list-incident-updates",
        "get-incident-update",
        "create-incident-update",
        "update-incident-update",
        "delete-incident-update",
    }:
        if incident_id_raw is None:
            print(
                "PHARE_INCIDENT_ID is required for incident update operations.",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            incident_id_int = int(incident_id_raw)
        except ValueError:
            print(
                f"Invalid PHARE_INCIDENT_ID value '{incident_id_raw}'.",
                file=sys.stderr,
            )
            sys.exit(1)

        if operation == "list-incident-updates":
            page = _parse_int_env("PHARE_PAGE", 1)
            per_page = _parse_int_env("PHARE_PER_PAGE", 20)
            try:
                data = list_incident_updates(
                    token=token,
                    project_id=project_id,
                    project_slug=project_slug,
                    incident_id=incident_id_int,
                    page=page,
                    per_page=per_page,
                )
            except IncidentApiError as exc:
                print(str(exc), file=sys.stderr)
                sys.exit(1)
            with open(artifact_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"Listed incident updates for incident {incident_id_int}.")
            return

        if operation == "get-incident-update":
            if incident_update_id_raw is None:
                print("PHARE_INCIDENT_UPDATE_ID is required.", file=sys.stderr)
                sys.exit(1)
            try:
                iu_id = int(incident_update_id_raw)
            except ValueError:
                print("Invalid PHARE_INCIDENT_UPDATE_ID.", file=sys.stderr)
                sys.exit(1)
            try:
                data = get_incident_update(
                    token=token,
                    project_id=project_id,
                    project_slug=project_slug,
                    incident_id=incident_id_int,
                    incident_update_id=iu_id,
                )
            except IncidentApiError as exc:
                print(str(exc), file=sys.stderr)
                sys.exit(1)
            with open(artifact_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            if github_output:
                with open(github_output, "a", encoding="utf-8") as f:
                    f.write(f"incident_update_id={data.get('id', iu_id)}\n")
            print(f"Fetched incident update {iu_id}.")
            return

        if operation == "create-incident-update":
            if not update_state or not update_content:
                print(
                    "PHARE_UPDATE_STATE and PHARE_UPDATE_CONTENT are required.",
                    file=sys.stderr,
                )
                sys.exit(1)
            try:
                data = create_incident_update(
                    token=token,
                    project_id=project_id,
                    project_slug=project_slug,
                    incident_id=incident_id_int,
                    state=update_state,
                    content=update_content,
                    published_at=update_published_at,
                )
            except IncidentApiError as exc:
                print(str(exc), file=sys.stderr)
                sys.exit(1)
            with open(artifact_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            iu_id = data.get("id")
            if github_output and iu_id is not None:
                with open(github_output, "a", encoding="utf-8") as f:
                    f.write(f"incident_update_id={iu_id}\n")
            print("Created incident update.")
            return

        if operation == "update-incident-update":
            if incident_update_id_raw is None:
                print("PHARE_INCIDENT_UPDATE_ID is required.", file=sys.stderr)
                sys.exit(1)
            try:
                iu_id = int(incident_update_id_raw)
            except ValueError:
                print("Invalid PHARE_INCIDENT_UPDATE_ID.", file=sys.stderr)
                sys.exit(1)
            try:
                data = update_incident_update(
                    token=token,
                    project_id=project_id,
                    project_slug=project_slug,
                    incident_id=incident_id_int,
                    incident_update_id=iu_id,
                    state=update_state,
                    content=update_content,
                    published_at=update_published_at,
                )
            except IncidentApiError as exc:
                print(str(exc), file=sys.stderr)
                sys.exit(1)
            with open(artifact_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            if github_output:
                iu_out = data.get("id", iu_id)
                with open(github_output, "a", encoding="utf-8") as f:
                    f.write(f"incident_update_id={iu_out}\n")
            print("Updated incident update.")
            return

        if operation == "delete-incident-update":
            if incident_update_id_raw is None:
                print("PHARE_INCIDENT_UPDATE_ID is required.", file=sys.stderr)
                sys.exit(1)
            try:
                iu_id = int(incident_update_id_raw)
            except ValueError:
                print("Invalid PHARE_INCIDENT_UPDATE_ID.", file=sys.stderr)
                sys.exit(1)
            try:
                delete_incident_update(
                    token=token,
                    project_id=project_id,
                    project_slug=project_slug,
                    incident_id=incident_id_int,
                    incident_update_id=iu_id,
                )
            except IncidentApiError as exc:
                print(str(exc), file=sys.stderr)
                sys.exit(1)
            with open(artifact_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "incident_id": incident_id_int,
                        "incident_update_id": iu_id,
                        "lifecycle_status": "deleted",
                    },
                    f,
                    indent=2,
                )
            print("Deleted incident update.")
            return

    if operation == "create":
        try:
            incident = create_incident(
                token=token,
                project_id=project_id,
                project_slug=project_slug,
                impact=impact,
                title=title,
                description=description,
                exclude_from_downtime=exclude_from_downtime,
                incident_at=incident_at,
                recovery_at=recovery_at,
                monitors=monitors,
            )
        except IncidentApiError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump({**incident, "lifecycle_status": "active"}, f, indent=2)

        incident_id = incident.get("id")

        if github_output and incident_id is not None:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"incident_id={incident_id}\n")

        if incident_id is not None:
            print(f"Created Phare.io incident with id {incident_id}.")
        else:
            print("Created Phare.io incident (no 'id' field found in response).")

        return

    if incident_id_raw is None:
        print(
            "PHARE_INCIDENT_ID is required for 'update', 'recover', and 'delete' operations.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        incident_id_int = int(incident_id_raw)
    except ValueError:
        print(
            f"Invalid PHARE_INCIDENT_ID value '{incident_id_raw}'. "
            "Expected a numeric incident id.",
            file=sys.stderr,
        )
        sys.exit(1)

    if operation == "update":
        try:
            incident = update_incident(
                token=token,
                project_id=project_id,
                project_slug=project_slug,
                incident_id=incident_id_int,
                impact=impact,
                title=title,
                description=description,
                exclude_from_downtime=exclude_from_downtime,
                incident_at=incident_at,
                recovery_at=recovery_at,
                monitors=monitors,
            )
        except IncidentApiError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump({**incident, "lifecycle_status": "active"}, f, indent=2)

        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"incident_id={incident_id_int}\n")

        print(f"Updated Phare.io incident with id {incident_id_int}.")
        return

    if operation == "recover":
        try:
            recover_incident(
                token=token,
                project_id=project_id,
                project_slug=project_slug,
                incident_id=incident_id_int,
            )
        except IncidentApiError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(
                {"id": incident_id_int, "lifecycle_status": "recovered"},
                f,
                indent=2,
            )

        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"incident_id={incident_id_int}\n")

        print(f"Recovered Phare.io incident with id {incident_id_int}.")
        return

    if operation == "delete":
        try:
            delete_incident(
                token=token,
                project_id=project_id,
                project_slug=project_slug,
                incident_id=incident_id_int,
            )
        except IncidentApiError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)

        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(
                {"id": incident_id_int, "lifecycle_status": "deleted"},
                f,
                indent=2,
            )

        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"incident_id={incident_id_int}\n")

        print(f"Deleted Phare.io incident with id {incident_id_int}.")
        return

    print(
        f"Unsupported operation '{operation}'. "
        "Supported: create, update, recover, delete, "
        "list-incident-updates, get-incident-update, create-incident-update, "
        "update-incident-update, delete-incident-update.",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
