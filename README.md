### Phare.io Incident GitHub Action

**[RChutchev/phare.io-incident-api](https://github.com/RChutchev/phare.io-incident-api)** — A lightweight GitHub Action that talks to the Phare.io Incident API to **create**, **update**, **recover**, and **delete** incidents from your CI/CD pipelines and store the incident details as GitHub Actions artifacts.

The action uses:

- **Create**: `POST /uptime/incidents` ([Create an incident](https://docs.phare.io/api-reference/uptime/incidents/create-an-incident)).
- **Update**: `POST /uptime/incidents/{incidentId}` ([Update an incident](https://docs.phare.io/api-reference/uptime/incidents/update-an-incident)).
- **Recover**: `POST /uptime/incidents/{incidentId}/recover` ([Recover a incident](https://docs.phare.io/api-reference/uptime/incidents/recover-an-incident)).
- **Delete**: `DELETE /uptime/incidents/{incidentId}` ([Delete an incident](https://docs.phare.io/api-reference/uptime/incidents/delete-an-incident)).

Under the hood, the action:

- **Calls** the Phare.io API over HTTPS with your token and optional project headers.
- **Creates** a maintenance (or other impact) incident with the fields you pass.
- **Writes** the full incident JSON response to `phare-incident.json`.
- **Uploads** `phare-incident.json` as a GitHub Actions artifact using `actions/upload-artifact` (see the GitHub docs for [storing and sharing data](https://docs.github.com/en/actions/tutorials/store-and-share-data)).
- **Exposes** the created incident id as the action output `incident-id`.

---

### Inputs

- **`phare-token`** (required): Phare.io API token.
  - **Best practice**: always pass this from a GitHub Secret, for example `secrets.PHARE_API_TOKEN`.
- **`project-id`** (optional): Sent as `X-Phare-Project-Id` header.
- **`project-slug`** (optional): Sent as `X-Phare-Project-Slug` header.
- **`impact`** (optional): Incident impact, default is `maintenance`.
  - Allowed values: `unknown`, `operational`, `degraded_performance`, `partial_outage`, `major_outage`, `maintenance`. These match the `Uptime.Incident.ImpactEnum` enum in the Phare API.
- **`title`** (optional): Incident title. For `operation: create`, if omitted a maintenance placeholder like `"Maintenance window"` is used.
- **`description`** (optional): Incident description. For `operation: create`, if omitted a maintenance placeholder like `"Automatic maintenance incident created by CI/CD pipeline."` is used.
- **`exclude-from-downtime`** (optional): Whether to exclude from downtime calculations (`true` / `false` / `1` / `0` / `yes` / `no`).
- **`monitors`** (optional): Comma-separated list of monitor IDs, e.g. `"1,2,3"`. Each ID is sent as an integer in the `monitors` array.
- **`incident-at`** (optional): Incident confirmation time (for create or update).
- **`recovery-at`** (optional): Incident recovery time (for create or update).
- **`incident-id`** (optional): ID of the incident to **update**, **recover**, or **delete**. Required for `operation: update`, `operation: recover`, and `operation: delete`.
- **`operation`** (optional): Operation to perform: `create`, `update`, `recover`, or `delete`.
- **`incident-artifact-name`** (optional): Name of the GitHub Actions artifact that will contain the created incident JSON. Defaults to `phare-incident`.

---

### Datetime input format (`incident-at`, `recovery-at`)

Both `incident-at` and `recovery-at` accept:

- **Absolute datetime**: ISO 8601 string, for example:
  - `2026-03-08T10:00:00Z`
  - `2026-03-08T10:00:00+00:00`
- **Relative offset from current time (UTC)**:
  - `10s` → current time + 10 seconds
  - `10m` → current time + 10 minutes
  - `1h` → current time + 1 hour
  - `10h` → current time + 10 hours
  - `1d` → current time + 1 day

The action normalizes all datetime values to UTC and sends them to Phare.io in ISO 8601 format with a `Z` suffix (for example `2026-03-08T10:00:00Z`), matching the `date-time` format expected by the Phare API as described in the [Create an incident](https://docs.phare.io/api-reference/uptime/incidents/create-an-incident) documentation.

If a datetime value is invalid, the action fails fast with a clear error message instead of sending bad data to the API.

---

### Security

- **Never hard-code** your Phare.io API token into workflows or code.
- Always pass it via **GitHub Secrets**:
  - `phare-token: ${{ secrets.PHARE_API_TOKEN }}`
- Optional project headers (`project-id`, `project-slug`) can also come from secrets or repository/organization variables.
- The action **never logs** the token or headers; it only logs high-level status like the created incident id.

---

### Example 1: Create a maintenance incident at the start of CI/CD

This example shows a typical CI/CD use case:

- At the very start of the pipeline, the workflow creates a **maintenance incident** in Phare.io.
- The incident is scheduled to **start immediately** and to **recover 1 hour later**.
- The full incident payload is stored as an artifact named `phare-incident`, which can be downloaded and used by later jobs or workflows (see [GitHub artifact docs](https://docs.github.com/en/actions/tutorials/store-and-share-data)).

```yaml
name: Deploy with Phare.io maintenance

on:
  push:
    branches: [ main ]

jobs:
  create_maintenance_incident:
    runs-on: ubuntu-latest
    steps:
      - name: Create Phare.io maintenance incident
        uses: RChutchev/phare.io-incident-api@v1
        with:
          phare-token: ${{ secrets.PHARE_API_TOKEN }}
          project-id: ${{ secrets.PHARE_PROJECT_ID }} # or use project-slug
          impact: maintenance
          title: "Scheduled deployment"
          description: "CI/CD deployment from GitHub Actions."
          exclude-from-downtime: true
          monitors: "1,2,3"
          # start incident now, mark recovery 1 hour later
          incident-at: "0s"
          recovery-at: "1h"
          incident-artifact-name: "phare-incident"

      # ... your CI/CD steps here ...
```

The artifact created by the action (`phare-incident.json`) contains the full Phare.io incident resource as returned by the API (including fields like `id`, `slug`, `state`, `impact`, etc.), matching the `Uptime.Incident.Resource` schema from the [Phare API documentation](https://docs.phare.io/api-reference/uptime/incidents/create-an-incident).

You can download and reuse this artifact from another job or workflow using `actions/download-artifact`, as described in the GitHub documentation for [storing and sharing data](https://docs.github.com/en/actions/tutorials/store-and-share-data).

---

### Artifact lifecycle and operation eligibility

The action adds a `lifecycle_status` field to every artifact so you can safely decide which operations to run. **Always check `lifecycle_status` before calling update, recover, or delete**—otherwise you may operate on an already-recovered or deleted incident and break your CI/CD.

| `lifecycle_status` | Meaning | Update | Recover | Delete |
|--------------------|---------|--------|---------|--------|
| `active` | Incident was created or updated | ✅ | ✅ | ✅ |
| `recovered` | Incident was recovered | ⚠️ * | ❌ | ✅ |
| `deleted` | Incident was deleted | ❌ | ❌ | ❌ |

\* **Update on recovered**: The Phare API may allow updating a recovered incident (e.g. to change metadata). If it works for your use case, you can run update when `lifecycle_status` is `recovered` as well. Test in your environment.

**Rules to avoid broken CI/CD:**

- **Update**: Only when `lifecycle_status == "active"` (created or updated). Do not update a deleted incident.
- **Recover**: Only when `lifecycle_status == "active"`. Do not recover an already-recovered or deleted incident.
- **Delete**: Only when `lifecycle_status == "active"` or `"recovered"`. Do not delete an already-deleted incident (Phare returns 404).

When downloading artifacts from another workflow run, you may receive an artifact from a previous pipeline that already recovered or deleted the incident. Use the conditional examples below to guard against this.

---

### Example 2: Update an existing incident in the same workflow

You can use the `incident-id` output from a previous step to update the same incident in the same workflow:

```yaml
jobs:
  deploy_with_incident:
    runs-on: ubuntu-latest
    steps:
      - name: Create maintenance incident
        id: create_incident
        uses: RChutchev/phare.io-incident-api@v1
        with:
          phare-token: ${{ secrets.PHARE_API_TOKEN }}
          project-id: ${{ secrets.PHARE_PROJECT_ID }}
          impact: maintenance
          # title/description optional; maintenance placeholders used by default

      - name: Start deployment (update incident title and description)
        uses: RChutchev/phare.io-incident-api@v1
        with:
          phare-token: ${{ secrets.PHARE_API_TOKEN }}
          project-id: ${{ secrets.PHARE_PROJECT_ID }}
          operation: update
          incident-id: ${{ steps.create_incident.outputs.incident-id }}
          title: "Deployment in progress"
          description: "CI/CD deployment is currently running."
```

Only the fields you pass for `operation: update` are changed; the others stay as they are in Phare.io, matching the behavior of [Update an incident](https://docs.phare.io/api-reference/uptime/incidents/update-an-incident).

---

### Example 3: Recover an incident in a separate workflow using artifacts

In many production setups, the workflow that **creates** the incident is not the same as the one that **recovers** it. You can use GitHub’s artifact APIs to pass the incident id between workflows, as described in [store and share data between workflows](https://docs.github.com/en/actions/tutorials/store-and-share-data).

**Workflow A** (create the incident and run the pipeline):

```yaml
name: Pipeline with Phare.io incident

on:
  push:
    branches: [ main ]

jobs:
  build_and_deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Create Phare.io incident
        id: create_incident
        uses: RChutchev/phare.io-incident-api@v1
        with:
          phare-token: ${{ secrets.PHARE_API_TOKEN }}
          project-id: ${{ secrets.PHARE_PROJECT_ID }}
          impact: maintenance
          incident-artifact-name: "phare-incident"

      # ... your CI/CD steps here ...
```

This job uploads:

- A `phare-incident` artifact containing `phare-incident.json` with the full incident resource.
- An output `incident-id` on the `create_incident` step you can reuse in the same workflow.

**Workflow B** (recover or delete the incident, with lifecycle checks):

Split recover and delete into **separate jobs** so only one runs (success → recover, failure → delete). Each job downloads the artifact, checks `lifecycle_status`, and runs the action only when the incident is in the correct state.

```yaml
name: Recover or delete Phare.io incident

on:
  workflow_run:
    workflows: ["Pipeline with Phare.io incident"]
    types: [completed]

jobs:
  on_success_recover:
    if: github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-latest
    steps:
      - name: Download incident artifact
        uses: actions/download-artifact@v5
        with:
          name: phare-incident
          path: artifacts
          run-id: ${{ github.event.workflow_run.id }}

      - name: Extract incident id and lifecycle status
        id: incident_meta
        run: |
          ARTIFACT="artifacts/phare-incident.json"
          incident_id=$(jq -r '.id' "$ARTIFACT")
          lifecycle=$(jq -r '.lifecycle_status // "active"' "$ARTIFACT")
          echo "incident_id=$incident_id" >> "$GITHUB_OUTPUT"
          echo "lifecycle_status=$lifecycle" >> "$GITHUB_OUTPUT"

      - name: Recover incident in Phare.io
        if: steps.incident_meta.outputs.lifecycle_status == 'active'
        uses: RChutchev/phare.io-incident-api@v1
        with:
          phare-token: ${{ secrets.PHARE_API_TOKEN }}
          project-id: ${{ secrets.PHARE_PROJECT_ID }}
          operation: recover
          incident-id: ${{ steps.incident_meta.outputs.incident_id }}

  on_failure_delete:
    if: github.event.workflow_run.conclusion == 'failure'
    runs-on: ubuntu-latest
    steps:
      - name: Download incident artifact
        uses: actions/download-artifact@v5
        with:
          name: phare-incident
          path: artifacts
          run-id: ${{ github.event.workflow_run.id }}

      - name: Extract incident id and lifecycle status
        id: incident_meta
        run: |
          ARTIFACT="artifacts/phare-incident.json"
          incident_id=$(jq -r '.id' "$ARTIFACT")
          lifecycle=$(jq -r '.lifecycle_status // "active"' "$ARTIFACT")
          echo "incident_id=$incident_id" >> "$GITHUB_OUTPUT"
          echo "lifecycle_status=$lifecycle" >> "$GITHUB_OUTPUT"

      - name: Delete incident in Phare.io
        if: steps.incident_meta.outputs.lifecycle_status == 'active' || steps.incident_meta.outputs.lifecycle_status == 'recovered'
        uses: RChutchev/phare.io-incident-api@v1
        with:
          phare-token: ${{ secrets.PHARE_API_TOKEN }}
          project-id: ${{ secrets.PHARE_PROJECT_ID }}
          operation: delete
          incident-id: ${{ steps.incident_meta.outputs.incident_id }}
```

**Note:** Downloading artifacts from another workflow run requires `actions/download-artifact` with a `run-id` or `workflow_run` token—see [Download Artifacts from other Workflow Runs](https://github.com/actions/download-artifact?tab=readme-ov-file#download-artifacts-from-other-workflow-runs-or-repositories). The `workflow_run` trigger above is one way to run this after your main pipeline completes.

The `if` conditions ensure:

- **Recover** runs only when `lifecycle_status == "active"`. It will not run on an already-recovered or deleted incident.
- **Delete** runs only when `lifecycle_status` is `"active"` or `"recovered"`. It will not run on an already-deleted incident (avoids 404).

For **update** (e.g. during deployment in the same workflow), only run when `lifecycle_status == "active"`:

```yaml
      - name: Update incident during deployment
        if: steps.incident_meta.outputs.lifecycle_status == 'active'
        uses: RChutchev/phare.io-incident-api@v1
        with:
          phare-token: ${{ secrets.PHARE_API_TOKEN }}
          project-id: ${{ secrets.PHARE_PROJECT_ID }}
          operation: update
          incident-id: ${{ steps.incident_meta.outputs.incident_id }}
          title: "Deployment in progress"
```

**Backward compatibility:** Artifacts from older runs may not have `lifecycle_status`. The example uses `jq -r '.lifecycle_status // "active"'` so missing `lifecycle_status` is treated as `active`.

**Artifact format after each operation:**

- After **create** or **update**: full incident plus `"lifecycle_status": "active"`.
- After **recover**: `{ "id": 123, "lifecycle_status": "recovered" }`.
- After **delete**: `{ "id": 123, "lifecycle_status": "deleted" }`.

The `lifecycle_status` field lets you safely reuse the artifact across runs without operating on an incident that was already recovered or deleted by a previous pipeline.

---

### Development

- **Package layout:** The package uses the [src layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) (`src/incident_api/`). Tests import the installed `incident_api` package.
- **Install & run:** The action and local dev use [uv](https://docs.astral.sh/uv/) (fast Python package installer). Install with `uv sync` (or `uv pip install -e .`). Run the CLI with `uv run python -m incident_api`. For reproducible CI, run `uv lock` and commit `uv.lock`.
- **Tests:** `pytest` (see `pyproject.toml`). Run with `uv run pytest` or `pytest`. Tests cover parsing helpers and the create/update/recover/delete API calls via mocked `requests`.
- **Type checking:** Optional [Pyright](https://microsoft.github.io/pyright/) config is in `pyproject.toml` under `[tool.pyright]`. Run with `pyright` if installed.

