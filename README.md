# GitHub Copilot Audit Sentinel

Production-oriented proof of concept that retains complete GitHub Enterprise
Copilot audit records in Microsoft Sentinel while deriving normalized metadata
for efficient hunting and dashboards.

> [!WARNING]
> `GitHubCopilotAudit_CL.RawEvent` can contain credentials, Authorization
> headers, prompts, source code, model output, tool arguments, personal data,
> IP addresses, and device/session identifiers. Restrict workspace and table
> access to the security team, use the shortest investigation-compatible
> retention, control exports, and treat query results as sensitive evidence.

## Architecture

```text
GitHub Enterprise audit delivery
  -> ypycopilottest/github-copilot-audit-log
  -> Event Grid BlobCreated (*.json.log.gz)
  -> Python 3.12 Azure Function (Flex Consumption, system identity)
       -> gzip/plain detection
       -> JSON object, array, or JSON Lines parsing
       -> exact/raw record retention with explicit encoding
       -> no-op-by-default transformation policy
       -> normalized metadata extraction
       -> UTF-8-safe raw chunking and bounded ingestion batches
  -> Direct Data Collection Rule
  -> GitHubCopilotAudit_CL
  -> Microsoft Sentinel workbook and KQL
```

Infrastructure is composed from the official Azure Functions
`blob-eventgrid-trigger-python-azd` AZD/Bicep template. The separate Function
runtime storage account has shared-key access and public anonymous Blob access
disabled. The public storage endpoint remains network-reachable because Flex
Consumption OneDeploy requires it in this non-VNet architecture; all data-plane
operations still require Microsoft Entra authorization. The Function uses its
system-assigned identity for runtime/deployment storage, source container
reads, Application Insights authentication, and DCR ingestion.

The inherited `StorageAccount_PublicNetwork_Modify` policy normally rewrites
storage public network access to `Disabled`. Its documented resource-level
exclusion tag, `SecurityControl=Ignore`, is applied only to the dedicated
runtime/deployment account so the required `Enabled` setting persists.
Shared keys, anonymous Blob access, and TLS versions below 1.2 remain disabled,
and OAuth is the default authentication mode. The deployment principal does
not receive a storage data role. Environments that cannot permit this narrowly
scoped endpoint must instead add Flex VNet integration, a Blob private
endpoint, and private DNS before disabling public network access.

## Lossless raw-record contract

The default transform is identity/no-op. No source field is selected, omitted,
masked, or truncated:

- A root JSON object retains its original decoded text, including whitespace.
- Each JSONL record retains its exact line text; `SourceRecordIndex` is its
  zero-based physical line index.
- JSON array elements retain their exact source token, including duplicate
  properties, while the parsed view is used only for normalized metadata.
- Malformed text retains its exact record text.
- Invalid UTF-8 and corrupt gzip bytes are base64 encoded.
- `RawEncoding` states how to interpret `RawEvent`.
- Raw values larger than 64,000 UTF-8 bytes are split without breaking a code
  point. Concatenate chunks ordered by `RawChunkIndex`; `RawChunkCount` states
  completeness.
  - `RawContentHash` versions the complete transformed representation so changed
    replays cannot be reconstructed with stale chunks.
- Compressed and decompressed blobs are bounded at 64 MiB. Content beyond a
  blob safety limit is explicitly marked `not-captured:<status>` rather than
  silently truncated or partially ingested.

`EventId`, `SourceBlob`, and `SourceRecordIndex` identify one source record.
All chunks of that record share `EventId` and `RawContentHash`; a unique
ingested row is identified by
`(EventId, RawContentHash, RawChunkIndex)`.

## Table schema

The DCR projects these fields into `GitHubCopilotAudit_CL`:

| Field | Type | Meaning |
|---|---|---|
| `TimeGenerated` | datetime | Source timestamp, or ingestion time with explicit status |
| `EventId` | string | SHA-256 of source blob path plus source record index |
| `GitHubRequestId` | string | Derived request identifier |
| `UserId` | string | Derived actor/user identifier |
| `EnterpriseId` | string | Derived enterprise identifier |
| `EventType` | string | Derived action or event type |
| `Endpoint` | string | Derived API endpoint |
| `Model` | string | Derived model name |
| `InteractionType` | string | Derived interaction category |
| `ToolNames` | string | JSON array of derived tool names |
| `StatusCode` | int | Derived response status |
| `SourceBlob` | string | Blob path, never a URL or SAS |
| `SourceRecordIndex` | int | Stable object/array/JSONL position |
| `PayloadBytes` | long | Original record size |
| `ParseStatus` | string | Parser/body/timestamp status |
| `IngestedAt` | datetime | UTC processing time |
| `RawEvent` | string | Complete raw/transformed payload chunk |
| `RawEncoding` | string | Raw representation and transform marker |
| `RawContentHash` | string | SHA-256 version of encoding plus complete transformed content |
| `RawChunkIndex` | int | Zero-based chunk position |
| `RawChunkCount` | int | Total chunks for the source record |

Normalized columns are derived for filtering only. `RawEvent` remains the audit
evidence and includes unknown/new fields automatically.

## Raw transformation policy

Policy code is isolated in `src/copilot_audit/transform.py`. The default is:

```text
RAW_TRANSFORM_POLICY=identity
```

This performs no redaction. An explicit example policy can be enabled later:

```text
RAW_TRANSFORM_POLICY=delete-top-level-fields
RAW_TRANSFORM_DELETE_FIELDS=authorization,headers
```

That policy is intentionally opt-in and fails closed on incompatible records;
it is never activated by this repository. Custom policies implement the
`RawTransform` callable and return `RawPayload`. Parsing, normalization,
chunking, batching, and ingestion do not need to be rewritten.

## Prerequisites and local validation

- Azure CLI, Azure Developer CLI, Azure Functions Core Tools, Python 3.12, and
  Bicep.
- Access to subscription `3456866f-6478-471f-8d59-a29a335d797a`.
- Contributor plus role-assignment write access on `aks-test` and the existing
  source container.
- Required Azure resource providers registered.
- Existing `ypycopilottest/github-copilot-audit-log` and GitHub Enterprise
  audit delivery.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m mypy src scripts
.\.venv\Scripts\python -m pytest
az bicep build --file infra/main.bicep
```

Fixtures are obviously synthetic. Never download real audit logs into this
repository. No deployment is performed by preparation or validation.

## Azure setup

After explicit deployment approval:

```powershell
azd auth login
azd env new copilot-audit-poc
azd env set AZURE_SUBSCRIPTION_ID 3456866f-6478-471f-8d59-a29a335d797a
azd env set AZURE_LOCATION westus2
azd env set EXISTING_EVENT_GRID_SYSTEM_TOPIC_NAME ypycopilottest-6a08b4cd-1cb5-4b03-af5d-5cc1ae92f536
azd provision --no-prompt
azd deploy --no-prompt
```

The source account already has the tracked system topic shown above. Supplying
its name makes Bicep treat Event Grid as existing: the deployment neither
updates nor replaces that topic or its `StorageAntimalwareSubscription`.
For a source storage account without a tracked topic, leave
`EXISTING_EVENT_GRID_SYSTEM_TOPIC_NAME` unset or empty and Bicep creates one.

The split sequence allows managed-identity RBAC propagation. The postdeploy
hook retrieves the platform-generated `blobs_extension` key only in memory to
create or update only this environment's deterministic
`egsub-copilot-audit-<token>` subscription. It leaves every other subscription
untouched and applies only BlobCreated events under
`github-copilot-audit-log` ending in `.json.log.gz`. The hook never prints,
commits, exports, or stores the key in application settings.

## Operations

Event Grid and Functions are at-least-once. Select one complete content version
before deduplicating its chunks; the canonical query is in
`sentinel/hunting-queries.kql`. A minimal query for unchanged replays is:

```kusto
GitHubCopilotAudit_CL
| extend ContentVersion=coalesce(RawContentHash, "legacy"),
         ChunkIndex=coalesce(RawChunkIndex, 0)
| summarize arg_max(IngestedAt, *) by EventId, ContentVersion, ChunkIndex
```

Count source events from chunk zero:

```kusto
GitHubCopilotAudit_CL
| where coalesce(RawChunkIndex, 0) == 0
| summarize arg_max(IngestedAt, *) by EventId
```

Reconstruct one complete record:

```kusto
let target_event_id = "<EventId>";
GitHubCopilotAudit_CL
| where EventId == target_event_id
| extend ContentVersion=coalesce(RawContentHash, "legacy"),
         ChunkIndex=coalesce(RawChunkIndex, 0)
| summarize arg_max(IngestedAt, *) by EventId, ContentVersion, ChunkIndex
| summarize LatestIngestedAt=max(IngestedAt),
            PresentChunks=dcount(ChunkIndex),
            ExpectedChunks=max(coalesce(RawChunkCount, 1))
            by EventId, ContentVersion
| where PresentChunks == ExpectedChunks
| top 1 by LatestIngestedAt desc
| join kind=inner (
    GitHubCopilotAudit_CL
    | where EventId == target_event_id
    | extend ContentVersion=coalesce(RawContentHash, "legacy"),
            ChunkIndex=coalesce(RawChunkIndex, 0)
) on EventId, ContentVersion
| summarize arg_max(IngestedAt, *) by EventId, ContentVersion, ChunkIndex
| order by ChunkIndex asc
| summarize RawEvent=strcat_array(make_list(RawEvent), ""),
            RawEncoding=any(RawEncoding),
            RawContentHash=any(RawContentHash)
```

Transient ingestion failures propagate for platform retry. Application
Insights receives counts, stages, and exception class names only—not raw
records or exception messages that might echo record content.

### Backfill

Backfill uses the same lossless transform, chunking, and batching path. It is
dry-run by default and requires explicit blobs or a date window of at most 31
days. `--max-blobs` defaults to 100 and has a hard maximum of 1,000.

```powershell
python scripts/backfill.py --blob audit/2026/08/19/example.json.log.gz
python scripts/backfill.py `
  --start 2026-08-01T00:00:00Z `
  --end 2026-08-08T00:00:00Z `
  --prefix audit/2026/08/ `
  --max-blobs 100
python scripts/backfill.py --blob audit/2026/08/19/example.json.log.gz --execute
```

The local identity needs source Blob Data Reader and DCR Monitoring Metrics
Publisher. Never use storage keys, SAS, PATs, application secrets, or workspace
shared keys.

## Sentinel security and retention

- `infra/workbook.json` contains normalized dashboards plus a clearly marked
  restricted raw-record preview.
- `sentinel/hunting-queries.kql` includes chunk-aware deduplication,
  reconstruction, parse health, anomaly, and tool-use queries.
- `sentinel/analytics-rules.kql` contains chunk-aware candidate rules.
- The POC retention is 30 days. Security owners must review this against data
  classification, legal hold, incident response, and credential-exposure
  requirements before deployment.
- Limit Log Analytics/Sentinel roles to the audit team, review query/export
  activity, and avoid copying raw records into tickets or lower-trust systems.
