# GitHub Copilot Audit Sentinel

Production-oriented proof of concept for routing privacy-sanitized GitHub
Enterprise Copilot audit metadata into Microsoft Sentinel. Raw audit content
stays in the existing private Blob container; only the schema documented below
is sent to Azure Monitor.

## Architecture

```text
GitHub Enterprise audit delivery
  -> ypycopilottest/github-copilot-audit-log
  -> Event Grid BlobCreated (*.json.log.gz)
  -> Python 3.12 Azure Function (Flex Consumption, system identity)
       -> gzip/plain detection
       -> JSON object, array, or JSON Lines parsing
       -> nested body parsing in memory
       -> strict metadata allowlist
       -> bounded Logs Ingestion API batches
  -> Direct Data Collection Rule
  -> GitHubCopilotAudit_CL
  -> Microsoft Sentinel workbook and KQL
```

Infrastructure is composed from the official Azure Functions
`blob-eventgrid-trigger-python-azd` AZD/Bicep template. The separate Function
runtime storage account has shared-key access and public blob access disabled.
The Function uses its system-assigned identity for runtime storage, source
container reads, Application Insights authentication, and DCR ingestion.

## Emitted schema

The DCR projects exactly these fields into `GitHubCopilotAudit_CL`:

| Field | Type | Meaning |
|---|---|---|
| `TimeGenerated` | datetime | Source timestamp, or ingestion time with an explicit parse status |
| `EventId` | string | SHA-256 of source blob path plus zero-based source record index |
| `GitHubRequestId` | string | Allowlisted GitHub request identifier |
| `UserId` | string | Allowlisted GitHub actor/user identifier |
| `EnterpriseId` | string | Allowlisted enterprise identifier |
| `EventType` | string | Audit action or event type |
| `Endpoint` | string | API endpoint metadata |
| `Model` | string | Model name metadata |
| `InteractionType` | string | Interaction category metadata |
| `ToolNames` | string | JSON-encoded array containing tool names only |
| `StatusCode` | int | Response status code |
| `SourceBlob` | string | Blob path, never a URL or SAS |
| `SourceRecordIndex` | int | Stable object/array/JSONL position |
| `PayloadBytes` | long | Encoded source-record size |
| `ParseStatus` | string | Explicit parser/body/timestamp status |
| `IngestedAt` | datetime | UTC processing time |

`body`, headers, authorization values, prompts, source code, model output, tool
arguments, IP addresses, device identifiers, and session identifiers are parsed
only when needed and are never emitted. Unknown fields are discarded rather
than copied. Malformed input produces a metadata-only row with a parse status;
the original bytes remain only in the source archive.

## Prerequisites

- Azure CLI, Azure Developer CLI, Azure Functions Core Tools, Python 3.12, and
  Bicep.
- Access to subscription `3456866f-6478-471f-8d59-a29a335d797a`.
- Contributor on resource group `aks-test`.
- User Access Administrator (or equivalent `roleAssignments/write`
  permission) on `aks-test` and the existing source container.
- The resource providers `Microsoft.Web`, `Microsoft.Storage`,
  `Microsoft.EventGrid`, `Microsoft.Insights`,
  `Microsoft.OperationalInsights`, `Microsoft.OperationsManagement`, and
  `Microsoft.SecurityInsights` registered in the subscription.
- The existing `ypycopilottest/github-copilot-audit-log` container and GitHub
  Enterprise audit delivery configured independently.

No deployment has been run by this repository preparation.

## Local validation

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy src scripts
.\.venv\Scripts\python -m pytest
az bicep build --file infra/main.bicep
```

Fixtures under `tests/fixtures` are synthetic. Do not download audit logs into
this repository or use production data in tests.

## Azure setup

After deployment approval, initialize an AZD environment and inspect the
generated parameter values before provisioning:

```powershell
azd auth login
azd env new copilot-audit-poc
azd env set AZURE_SUBSCRIPTION_ID 3456866f-6478-471f-8d59-a29a335d797a
azd env set AZURE_LOCATION westus2
azd provision --no-prompt
azd deploy --no-prompt
```

Preparation and validation do not execute these commands. The split provision
and deploy sequence is intentional so identity and role assignments can
propagate before code starts.

## Operations

The Blob trigger uses Event Grid and is filtered twice: the Event Grid
subscription accepts only BlobCreated events in the target container ending in
`.json.log.gz`, and the Python v2 trigger path applies the same container and
suffix boundary. Compressed input and decompressed content are each capped at
64 MiB; larger inputs become metadata-only parse-status rows.

Azure Functions event-based Blob triggers require the platform's
`blobs_extension` system-key webhook. The AZD postdeploy hook retrieves this
runtime-generated key only after code deployment, creates or updates the
filtered Event Grid subscription, and clears the local variable. The key is
never committed, printed, exported by Bicep, or placed in application settings.
The deployment principal therefore needs Function host-key read permission and
Event Grid event-subscription write permission.

Event Grid and Azure Functions provide at-least-once processing. `EventId` is
stable for the same blob path and source position. Queries should deduplicate
before analysis:

```kusto
GitHubCopilotAudit_CL
| summarize arg_max(IngestedAt, *) by EventId
```

Transient Azure SDK failures are not swallowed; they propagate to the Functions
host for platform retry. Logs contain counts and exception class names only,
never blob payloads, record values, blob names, or exception messages.

### Backfill

Backfill is dry-run by default and refuses unbounded container replay. Select
either explicit blobs or a date window no longer than 31 days; all runs are
capped by `--max-blobs` (hard maximum 1,000).

```powershell
# Dry-run an explicit selection
python scripts/backfill.py --blob audit/2026/08/19/example.json.log.gz

# Dry-run a bounded date/prefix selection
python scripts/backfill.py `
  --start 2026-08-01T00:00:00Z `
  --end 2026-08-08T00:00:00Z `
  --prefix audit/2026/08/ `
  --max-blobs 100

# Add --execute only after reviewing the printed selection
python scripts/backfill.py --blob audit/2026/08/19/example.json.log.gz --execute
```

Local backfill uses the developer's Azure identity. It requires source Blob
Data Reader access and Monitoring Metrics Publisher on the DCR. Never use keys,
SAS, workspace shared keys, PATs, or application secrets.

## Sentinel content

- `infra/workbook.json` is deployed as a shared Sentinel workbook.
- `sentinel/hunting-queries.kql` contains deduplication, parse health, anomalous
  volume, model/endpoint, and tool-use hunts.
- `sentinel/analytics-rules.kql` contains starting queries for scheduled
  analytics rules. Tune thresholds against a representative sanitized baseline
  before enabling incidents.

## Privacy operations

Access to the raw source account should remain more restrictive than access to
the Sentinel workspace. Treat `UserId`, `EnterpriseId`, `GitHubRequestId`, and
`SourceBlob` as organizational metadata and apply workspace RBAC accordingly.
Use Azure Activity Logs to review RBAC changes. Do not log payloads while
debugging; reproduce parser issues with a new synthetic fixture instead.
