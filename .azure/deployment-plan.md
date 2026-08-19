# Azure Deployment Plan

> **Status:** Planning

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

### Identity and RBAC

- System-assigned Function managed identity.
- `Storage Blob Data Reader` scoped to the existing source container.
- Required runtime storage data roles scoped to the new Function storage
  account.
- `Monitoring Metrics Publisher` scoped to the DCR.
- Event Grid delivery authorization scoped only to the Function endpoint.
- No Key Vault is needed because the design has no application secrets.

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
- [ ] User approved this plan

### Phase 2: Execution

- [ ] Load Azure Functions template selection and composition rules
- [ ] Compose official Flex Consumption + Event Grid Blob trigger templates
- [ ] Generate Python Function, parser, sanitizer, and ingestion client
- [ ] Generate Log Analytics table, Direct DCR, Sentinel, and workbook IaC
- [ ] Add managed identity and least-privilege RBAC
- [ ] Add unit, parser-fixture, sanitizer, idempotency, and integration tests
- [ ] Add payload-safe Application Insights telemetry
- [ ] Add backfill utility and operator documentation
- [ ] Add CI for lint, type checking, security scanning, and tests
- [ ] Update status to `Ready for Validation`

### Phase 3: Validation

- [ ] Invoke `azure-validate`
- [ ] Verify Bicep, AZD configuration, Python tests, and security controls
- [ ] Confirm fixtures contain no real audit data or credentials
- [ ] Update status to `Validated`
- [ ] Record validation proof below

### Phase 4: Deployment

- [ ] Invoke `azure-deploy` only after explicit deployment approval
- [ ] Verify Event Grid delivery, custom-table ingestion, and workbook queries
- [ ] Update status to `Deployed`

---

## 8. Validation Proof

| Check | Command Run | Result | Timestamp |
|-------|-------------|--------|-----------|
| Pending | Pending validation | Pending | Pending |

**Validated by:** Pending `azure-validate`

---

## 9. Files to Generate

| File | Purpose | Status |
|------|---------|--------|
| `.azure/deployment-plan.md` | Source-of-truth plan | Complete |
| `README.md` | Architecture, setup, privacy, and operations | Planned |
| `azure.yaml` | AZD service definition | Planned |
| `infra/` | Bicep resources, RBAC, DCR, Sentinel, workbook | Planned |
| `src/function_app.py` | Event Grid Blob trigger entrypoint | Planned |
| `src/copilot_audit/` | Parser, sanitizer, schema, ingestion client | Planned |
| `sentinel/` | KQL hunting and analytics queries | Planned |
| `scripts/backfill.py` | Explicit historical replay | Planned |
| `tests/` | Synthetic fixtures and automated tests | Planned |
| `.github/workflows/ci.yml` | Pull-request validation | Planned |

---

## 10. Current Step

Present this plan for user approval. No application code, infrastructure, or
deployment is permitted until approval is recorded.
