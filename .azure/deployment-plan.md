# Azure Deployment Plan

> **Status:** Validated

Generated: 2026-08-19

---

## 1. Project Overview

**Goal:** Build a secure, event-driven pipeline that reads GitHub Copilot audit
log blobs from the existing `ypycopilottest/github-copilot-audit-log`
container, parses and sanitizes the events, sends an allowlisted schema through
the Azure Monitor Logs Ingestion API, and provides Microsoft Sentinel queries,
analytics, and a workbook.

**Path:** New Project

**Repository:** `gaussye/github-copilot-audit-sentinel` (private)

---

## 2. Requirements

| Attribute | Value |
|-----------|-------|
| Classification | POC |
| Scale | Small, less than 1 GB/day |
| Budget | Balanced cost and reliability |
| Runtime | Python 3.12, Azure Functions v4 |
| Subscription | `ME-MngEnvMCAP566860-pengyongye-1` (`3456866f-6478-471f-8d59-a29a335d797a`) |
| Location | West US 2 |
| Source | Existing `ypycopilottest/github-copilot-audit-log` |
| Sentinel target | New dedicated Log Analytics workspace with Sentinel enabled |
| Compliance | No additional requirement; raw payload remains private in the source storage account |

### Security and Data Policy

- Use managed identities and Azure RBAC; do not store storage keys, SAS tokens,
  client secrets, or workspace shared keys.
- Treat `body`, `headers`, prompts, source code, model output, tool arguments,
  IP addresses, device IDs, and session IDs as sensitive.
- Use an allowlist sanitizer. Only approved scalar metadata is emitted.
- Never write raw payloads to Application Insights or exception messages.
- Retain the source blobs as the authoritative raw archive.
- Restrict the Function identity to read-only access on the existing source
  container and ingestion access on the DCR.

### Policy Constraints

The subscription has three Defender policies related to SQL Server data
protection and open-source relational databases. They do not restrict this
serverless architecture. No allowed-region, required-tag, resource-type, or
network-deny policy was detected.

---

## 3. Components

| Component | Type | Technology | Path |
|-----------|------|------------|------|
| Blob event processor | Worker | Azure Functions Python v2 model | `src/` |
| Audit parser | Library | Python gzip/JSON/JSON Lines parsing | `src/copilot_audit/` |
| Sanitizer | Library | Explicit allowlist and recursive discard policy | `src/copilot_audit/` |
| Sentinel ingestion client | Library | Azure Monitor Ingestion SDK + managed identity | `src/copilot_audit/` |
| Backfill utility | CLI | Python, explicit date/blob selection | `scripts/` |
| Infrastructure | IaC | AZD + Bicep | `infra/`, `azure.yaml` |
| Workbook and detections | Sentinel content | ARM/Bicep workbook and KQL | `infra/`, `sentinel/` |
| Tests | Validation | pytest | `tests/` |

---

## 4. Recipe Selection

**Selected:** AZD with Bicep

**Rationale:**

- This is a new Azure-first, multi-resource project.
- AZD provides environment management and a single validated deployment path.
- Bicep supports cross-resource-group references to the existing source storage
  account and deployment of Log Analytics, DCR, Sentinel, and workbook assets.
- Azure Functions infrastructure will be composed from the official Flex
  Consumption base and Event Grid Blob trigger recipe, not handwritten from
  reference snippets.

---

## 5. Architecture

**Stack:** Serverless, event driven

```text
GitHub Enterprise
  -> existing private Blob container
  -> BlobCreated Event Grid subscription (*.json.log.gz)
  -> Python Azure Function (Flex Consumption)
       -> parse gzip/plain JSON and JSON Lines
       -> parse nested body JSON when valid
       -> allowlist metadata and discard sensitive payloads
       -> batch records
  -> Azure Monitor Logs Ingestion API
  -> Direct DCR transformation and routing
  -> GitHubCopilotAudit_CL in dedicated Log Analytics workspace
  -> Microsoft Sentinel analytics, hunting queries, and workbook
```

### Service Mapping

| Component | Azure Service | SKU / Configuration |
|-----------|---------------|---------------------|
| Event processor | Azure Functions | Flex Consumption FC1, Python 3.12, scale to zero |
| Trigger | Event Grid system topic/subscription | BlobCreated, container prefix and `.json.log.gz` suffix filters |
| Runtime state/package | Storage Account | StorageV2 Standard LRS, private containers |
| Monitoring | Workspace-based Application Insights | Payload-free operational telemetry |
| Security monitoring store | Log Analytics Workspace | Pay-as-you-go, 30-day POC retention |
| SIEM | Microsoft Sentinel | Enabled on dedicated workspace |
| Ingestion | Direct Data Collection Rule | Logs Ingestion endpoint, managed identity authorization |
| Visualization | Azure Workbook | Copilot activity and pipeline health |

### Target Table Schema

The custom `GitHubCopilotAudit_CL` table will contain only:

- `TimeGenerated`
- `EventId`
- `GitHubRequestId`
- `UserId`
- `EnterpriseId`
- `EventType`
- `Endpoint`
- `Model`
- `InteractionType`
- `ToolNames` (JSON-encoded string array)
- `StatusCode`
- `SourceBlob`
- `SourceRecordIndex`
- `PayloadBytes`
- `ParseStatus`
- `IngestedAt`

The DCR performs final type conversion and projects exactly this schema. It
does not receive raw `body` or `headers`.

### Reliability

- Event Grid provides at-least-once delivery and retry.
- Event IDs plus source blob/index form deterministic identifiers.
- Workbook and hunting queries deduplicate with `arg_max()` by deterministic ID.
- Transient ingestion failures raise errors for Function/Event Grid retry.
- Permanently malformed records emit metadata-only parse failures; raw content
  remains available in the original blob for authorized investigation.
- A backfill utility supports explicit historical replay without changing the
  live trigger.
- Compressed and decompressed payloads are independently capped at 64 MiB.

### Identity and RBAC

- System-assigned Function managed identity.
- `Storage Blob Data Reader` scoped to the existing source container.
- Required runtime storage data roles scoped to the new Function storage
  account.
- `Monitoring Metrics Publisher` scoped to the DCR.
- Event Grid delivery authorization scoped only to the Function endpoint.
- No Key Vault is needed because the design has no application secrets.
- The Functions platform-generated `blobs_extension` system key is retrieved
  transiently by the official-template postdeploy hook because event-based Blob
  triggers require the blob-extension webhook. It is not committed, logged,
  exported, or stored in application settings.

### Workbook

The initial workbook will show:

- Request/response volume over time.
- Model and endpoint distribution.
- Active user counts without prompt or code content.
- Tool-name distribution.
- Parse and ingestion failures.
- Duplicate delivery rate.

---

## 6. Provisioning Limit Checklist

Quota CLI was used first. `Microsoft.Storage` returned supported quota data.
`Microsoft.Web` did not expose a usable resource quota, so current usage plus
official Azure service limits are used for Functions. Non-quota ARM resources
are validated against the general limit of 800 resources per resource type per
resource group.

| Resource Type | Number to Deploy | Total After Deployment | Limit / Quota | Notes |
|---------------|------------------|------------------------|---------------|-------|
| Resource group | 1 | 39 | 980/subscription | Current usage 38; official ARM limit |
| `Microsoft.Storage/storageAccounts` | 1 | 7 in West US 2 | 250/region | Azure quota CLI: usage 6, available 244 |
| `Microsoft.Web/sites` (Function App) | 1 | 3 in West US 2 | 100 Function Apps/region | Current regional sites 2; official Functions limit |
| `Microsoft.Web/serverfarms` (FC1) | 1 | 4 in West US 2 | 800/type/resource group | Current regional plans 3; general ARM limit |
| `Microsoft.OperationalInsights/workspaces` | 1 | 14/subscription | 250/subscription | Current workspaces 13; official service limit |
| `Microsoft.Insights/components` | 1 | 4 in West US 2 | 800/type/resource group | Current regional components 3 |
| `Microsoft.Insights/dataCollectionRules` | 1 | 1 in West US 2 | 800/type/resource group | Current regional DCRs 0 |
| `Microsoft.OperationalInsights/workspaces/tables` | 1 | 1 planned | 800/type/resource group | One custom table |
| `Microsoft.OperationsManagement/solutions` | 1 | 1 in West US 2 | 800/type/resource group | Enables Sentinel; current regional solutions 0 |
| `Microsoft.Insights/workbooks` | 1 | 1 in West US 2 | 800/type/resource group | Current regional workbooks 0 |
| `Microsoft.EventGrid/systemTopics` | 1 | 1 planned | 800/type/resource group | Existing source storage integration |
| Event Grid subscription | 1 | 1 planned | 500/system topic | Filtered BlobCreated delivery |
| RBAC role assignments | Up to 6 | Up to 144/subscription | 4,000/subscription | Current assignments 138 |

**Status:** All planned resources are within limits.

---

## 7. Execution Checklist

### Phase 1: Planning

- [x] Create deployment plan before code or infrastructure
- [x] Analyze workspace as a new project
- [x] Gather classification, scale, budget, and compliance requirements
- [x] Confirm subscription and location
- [x] Check subscription policies
- [x] Prepare resource inventory
- [x] Invoke Azure Quotas and validate capacity
- [x] Select AZD/Bicep recipe
- [x] Plan architecture and sensitive-data policy
- [x] User approved this plan

### Phase 2: Execution

- [x] Load Azure Functions template selection and composition rules
- [x] Compose official Flex Consumption + Event Grid Blob trigger templates
- [x] Generate Python Function, parser, sanitizer, and ingestion client
- [x] Generate Log Analytics table, Direct DCR, Sentinel, and workbook IaC
- [x] Add managed identity and least-privilege RBAC
- [x] Add unit, parser-fixture, sanitizer, idempotency, and integration tests
- [x] Add payload-safe Application Insights telemetry
- [x] Add backfill utility and operator documentation
- [x] Add CI for lint, type checking, security scanning, and tests
- [x] Update status to `Ready for Validation`

### Phase 3: Validation

- [x] Invoke `azure-validate`
- [x] All validation checks pass
  - [x] AZD installation and schema
  - [x] AZD environment, authentication, subscription, and location
  - [x] AZD provision preview
  - [x] Python build, lint, type check, tests, and package
  - [x] Bicep compilation, lint, template validation, and what-if
  - [x] Azure Policy compatibility
  - [x] Static least-privilege role verification
  - [x] JSON, YAML, hook syntax, dependency, and credential-artifact checks
- [x] Confirm fixtures contain no real audit data or credentials
- [x] Update status to `Validated`
- [x] Record validation proof below

### Phase 4: Deployment

- [ ] Invoke `azure-deploy` only after explicit deployment approval
- [ ] Verify Event Grid delivery, custom-table ingestion, and workbook queries
- [ ] Update status to `Deployed`

---

## 8. Validation Proof

| Check | Command Run | Result | Timestamp |
|-------|-------------|--------|-----------|
| AZD/auth/context | `azd version`; `azd auth login --check-status`; `azd env get-values`; `az account show` | Passed; AZD 1.28.1, authenticated, approved subscription and `westus2` | 2026-08-19T10:54:25+08:00 |
| Provision preview | `azd provision --preview --no-prompt` | Passed; preview only, no changes applied | 2026-08-19T10:54:25+08:00 |
| Bicep | `az bicep build`; `az bicep lint` | Passed without compile or lint errors | 2026-08-19T10:54:25+08:00 |
| ARM validation | `az deployment sub validate ...` | Succeeded; nested deployments short-circuited only where runtime references are unresolved during validation | 2026-08-19T10:54:25+08:00 |
| What-if | `az deployment sub what-if ...` | Succeeded; 18 creates, 30 existing resources ignored; no deployment | 2026-08-19T10:54:25+08:00 |
| Python quality | `ruff format --check`; `ruff check`; `mypy src scripts`; `pytest` | Passed; 26 tests | 2026-08-19T10:54:25+08:00 |
| Dependency audit | `python -m pip_audit -r src/requirements.txt` | No known vulnerabilities | 2026-08-19T10:54:25+08:00 |
| Package | `azd package --no-prompt` | Passed; Function package produced in the system temp directory | 2026-08-19T10:54:25+08:00 |
| Config/hooks | JSON/YAML parsing; PowerShell parser; `sh -n`; `git diff --check` | Passed | 2026-08-19T10:54:25+08:00 |
| Source/policy/RBAC | Source account/container queries; policy assignment review; role definition verification | Passed; source is StorageV2 in `westus2`; role IDs and least-privilege scopes verified | 2026-08-19T10:54:25+08:00 |
| Privacy | Credential-pattern/path scans; synthetic fixture scan; sanitizer leakage tests | Passed; no credential artifacts or real audit fixtures | 2026-08-19T10:54:25+08:00 |

**Validated by:** `azure-validate`

---

## 9. Files to Generate

| File | Purpose | Status |
|------|---------|--------|
| `.azure/deployment-plan.md` | Source-of-truth plan | Complete |
| `README.md` | Architecture, setup, privacy, and operations | Complete |
| `azure.yaml` | AZD service definition and Event Grid postdeploy hook | Complete |
| `infra/` | Bicep resources, RBAC, Direct DCR, Sentinel, workbook | Complete |
| `src/function_app.py` | Event Grid Blob trigger entrypoint | Complete |
| `src/copilot_audit/` | Parser, sanitizer, schema, ingestion client | Complete |
| `sentinel/` | KQL hunting and analytics queries | Complete |
| `scripts/backfill.py` | Explicit historical replay | Complete |
| `tests/` | Synthetic fixtures and automated tests | Complete |
| `.github/workflows/ci.yml` | Pull-request validation | Complete |

---

## 10. Current Step

Commit the validated preparation. Do not deploy Azure resources.

---

## 11. Implementation Research and Functional Verification

- **Official template:** `blob-eventgrid-trigger-python-azd` from
  `Azure-Samples/functions-quickstart-python-azd-eventgrid-blob`, composed at
  commit `6f6f56222c1e2d09226af2c686d4be18fc632264`.
- **Runtime:** Python 3.12 is supported by the 2026-08-06 Azure Functions
  templates manifest.
- **Blob delivery:** Current Microsoft guidance requires the blob-extension
  webhook for an Event Grid-backed Blob trigger; the subscription is therefore
  configured after code deployment by the official-template composition hook.
- **Logs ingestion:** Direct DCR API `2024-03-11` supplies its own Logs
  Ingestion endpoint; a DCE is not required without Azure Monitor Private Link.
- **Backend verification:** Parser, sanitizer, batching, bounded backfill,
  ingestion propagation, and payload-safe Function failure handling tested
  locally with synthetic data.
- **UI verification:** Not applicable; the only UI artifact is the declarative
  Sentinel workbook, whose JSON and embedded queries were parsed locally.

---

## 12. Remaining Deployment Prerequisites

- Register `Microsoft.OperationsManagement` and `Microsoft.SecurityInsights`;
  both are currently `NotRegistered`. Registration was intentionally not
  performed during preparation because it changes subscription configuration.
- The deployment principal needs Contributor plus role-assignment write access
  on `aks-test` and permission to read Function host system keys for the
  BlobTrigger Event Grid postdeploy hook.
- Obtain explicit deployment approval before invoking `azure-deploy`. No Azure
  resources were created or modified during preparation or validation.
