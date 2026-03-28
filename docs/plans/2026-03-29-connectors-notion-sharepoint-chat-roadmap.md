# MimirQ-nk9e 连接器生态路线图：Notion / SharePoint / 聊天来源

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define a practical roadmap for native connectors covering Notion, SharePoint, and chat-native sources, using the existing connector-run/config/state architecture and keeping the first milestones implementation-feasible.

**Architecture:** Reuse the current connector registry and connector-run model. Prioritize document-like sources that match the current ingestion semantics first, then layer on chat-native sources once ACL mapping, thread chunking, and attachment handling are specified clearly.

**Tech Stack:** Python, FastAPI, current connector framework, OAuth/service credentials, ACL inheritance, external source APIs

---

## Current MimirQ Baseline

Relevant repo anchors:

- `app/services/connector_registry.py`
  Existing connectors are document-like or catalog-like: URL batch, crawl, GitHub, Drive files, MinIO, Confluence, Jira, SQL catalog connectors.
- `docs/guides/connectors.md`
  The project already has a stable model for:
  - connector definitions,
  - validation,
  - run/config separation,
  - incremental and resume semantics,
  - connector state persistence.
- `docs/guides/connector_acl_inheritance.md`
  Source ACL to tenant-group inheritance already has a conceptual home.
- `app/rag/preprocessing/rule_packs.py`
  Existing rule packs already acknowledge exported Notion, Slack, and Teams artifacts, which means the ingestion pipeline has at least some cleanup awareness for these formats.

Current gap:

- there are no native connectors for Notion, SharePoint/OneDrive, Slack, or Teams.
- the question is not only API reachability, but also incremental sync, ACL inheritance, and chunking semantics.

## Priority Recommendation

Recommended delivery order:

1. Notion
2. SharePoint / OneDrive-backed document libraries
3. Slack
4. Teams

Why this order:

- Notion is the closest fit to current page/document ingestion patterns and likely fastest to land.
- SharePoint is strategically important but has more ACL and delta-sync complexity.
- Chat-native sources require thread-aware chunking, attachment correlation, and tighter privacy controls.
- Teams should come last because the compliance/export story is more complex than either Notion or Slack.

## Option Comparison by Source

| Source | Fit with current connector model | Main value | Main complexity | Recommendation |
| --- | --- | --- | --- | --- |
| Notion | High | Rich internal docs/wiki/database knowledge | Block tree traversal, partial ACL mapping, API limits | First |
| SharePoint / OneDrive | Medium-high | Enterprise document store with strong buyer pull | Microsoft Graph auth, delta sync, ACL inheritance, drive/site shape | Second |
| Slack | Medium | Chat knowledge, decision trails, Q&A history | Thread chunking, channel/user ACL, attachments, API/export limits | Third |
| Teams | Low-medium | Important in Microsoft-heavy orgs | Compliance/export rules, Graph scope complexity, conversation model | Fourth |

## Source-by-Source Recommendations

### 1. Notion

Recommended first connector scope:

- pages and block trees
- optionally database rows rendered into documents
- incremental sync via `last_edited_time`
- attachment/file blocks only if they already map cleanly to current document ingest

Keep out of the first POC:

- comments,
- workspace-wide mention graph,
- complex per-block permission edge cases.

Why first:

- conceptually similar to Confluence-style page ingestion,
- strong value for knowledge-base workloads,
- lower ACL complexity than SharePoint.

### 2. SharePoint / OneDrive

Recommended second connector scope:

- site + drive + document library traversal
- document files only in v1
- incremental sync through Graph delta or bounded polling, depending on the exact API surface chosen
- source ACL inheritance only for the principals that can be mapped reliably to tenant groups

Keep out of the first POC:

- custom list items as first-class documents,
- full SharePoint page rendering,
- every possible Microsoft 365 object type.

Why second:

- high enterprise value,
- but significantly more auth, delta, and ACL design work than Notion.

### 3. Slack

Recommended third connector scope:

- allowlisted public/private channels only
- thread-aware message export into conversation documents
- attachment references resolved through existing file/document paths where feasible
- bounded channel history windows and incremental checkpoints

Keep out of the first POC:

- full workspace crawl,
- DMs,
- admin/compliance-only history paths unless the customer explicitly provides that capability.

Why third:

- chat-native sources are valuable, but they force new chunking and permission semantics that the current connector framework does not yet fully encode.

### 4. Teams

Recommended fourth connector scope:

- only after SharePoint and Slack patterns are proven
- prefer document or export-backed ingestion over deep chat-native API dependence in the first pass

Why last:

- Teams chat access is often constrained by tenant policy, export/compliance setup, and Microsoft Graph permission complexity;
- attachment and conversation data frequently span multiple backing stores.

## Minimum POC Boundary per Connector

### Notion POC

- one workspace integration
- selected pages / databases only
- page content + child blocks
- incremental sync by edit timestamp
- workspace or page-level principal mapping only where stable

### SharePoint POC

- one site or one document library
- files only
- delta sync or bounded timestamp/paging strategy
- group/user ACL inheritance limited to mappable Graph principals

### Slack POC

- one to five allowlisted channels
- thread -> document materialization
- incremental checkpoint on message timestamp or cursor
- attachment links only if permissions and storage mapping are clear

### Teams POC

- do not start with native chat sync
- start with a feasibility review tied to customer compliance posture and export path

## Required Dependencies

1. OAuth / app registration and secret management
   Each connector needs an explicit credential and permission model; do not hide this under generic connector config.

2. External principal mapping
   Source ACL inheritance only works if external user/group ids can map to tenant groups.

3. Incremental cursor/state design
   The current connector state model is sufficient, but each new source needs a clearly defined cursor contract.

4. Conversation chunking policy
   Chat-native sources need a different chunk model than documents:
   - thread windowing
   - author/timestamp metadata
   - attachment references

5. Rate-limit and retry policy
   Notion, Microsoft Graph, Slack, and Teams all need source-specific throttling and backoff assumptions.

## Risks

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| ACL mismatch | Imported content may become overexposed or underexposed | Scope ACL inheritance conservatively and make mapping explicit |
| Incremental drift | Source cursors differ greatly by platform | Define source-specific state contracts before implementation |
| Chat noise | Raw chat history can degrade retrieval quality | Add thread-aware chunking and source-specific cleanup rules |
| Attachment sprawl | Messages often point to files stored elsewhere | Decouple message text ingest from attachment ingest in v1 |
| Operational support burden | Each SaaS source brings auth and tenant-specific failure modes | Start with the most document-like sources first |

## Rollout Steps

### Phase 1: Notion connector spec

- define config schema
- define page/block mapping
- define incremental cursor and ACL assumptions

### Phase 2: SharePoint connector spec

- define Graph scopes
- define site/drive/file traversal shape
- define ACL mapping and delta-sync assumptions

### Phase 3: Chat connector framework additions

- define thread chunking abstraction
- define attachment linkage model
- define per-message metadata schema and retention assumptions

### Phase 4: Slack then Teams

- implement Slack first as the simpler chat-native proving ground
- revisit Teams only when the export/compliance path is understood

## What Would Justify Closing `MimirQ-nk9e`

This issue can be closed once the team has:

- an ordered roadmap with Notion and SharePoint ahead of chat-native sources;
- explicit POC boundaries for each source family;
- documented assumptions for auth, incremental sync, ACL inheritance, and chunking;
- follow-on execution tickets that can be implemented source by source rather than reopening ecosystem discovery.

## References

- Notion block children API: `https://developers.notion.com/reference/get-block-children`
- Notion rate limits: `https://developers.notion.com/reference/request-limits`
- Microsoft Graph site list: `https://learn.microsoft.com/en-us/graph/api/site-list?view=graph-rest-1.0`
- Microsoft Graph drive item children: `https://learn.microsoft.com/en-us/graph/api/driveitem-list-children?view=graph-rest-1.0`
- OneDrive / SharePoint scan guidance: `https://learn.microsoft.com/en-us/onedrive/developer/rest-api/concepts/scan-guidance?view=odsp-graph-online`
- Microsoft Teams export guidance: `https://learn.microsoft.com/th-th/microsoftteams/export-teams-content`
