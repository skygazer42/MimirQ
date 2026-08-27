# Design Implementation Record: Knowledge Ingestion Operation

## Summary

- **Scope:** Page redesign
- **Target:** `web/app/knowledge/ingestion/operation-page-client.tsx`
- **Selected direction:** F — flat ingestion composer inside the existing MimirQ product shell
- **Preserved boundary:** Existing execution monitor remains implemented by `page-client.tsx`

## Implemented Changes

- [x] Replaced the dashboard/card stack with one compact two-column composer.
- [x] Kept all real dataset, local folder, URL, object storage, API, pipeline and upload handlers.
- [x] Added compact execution-path feedback for register, parse, govern and index stages.
- [x] Moved ingest mode, tags, collection and deduplication into progressive advanced settings.
- [x] Kept the existing `IngestionViewSwitch` and execution-monitor route.
- [x] Removed duplicate operation-page metrics and task monitoring.

## Files Changed

- `web/app/knowledge/ingestion/operation-page-client.tsx` — production composer and cleanup
- `web/app/knowledge/ingestion/operation-page-client.source.test.ts` — layout and capability contracts
- `web/app/knowledge/ingestion/operation-page-client.behavior.test.tsx` — rendered source/mode/submit behavior coverage
- `DESIGN_MEMORY.md` — durable product-design constraints

## Required UI States

- **No source content:** Natural next-step guidance and disabled primary action.
- **Ready:** Green preflight result and enabled action matching the execution endpoint.
- **Submitting:** Disabled action with spinner and submitting copy.
- **Completed/partial failure:** Previous successful/failed counts shown in the action summary.
- **Blocked connector:** Warning copy for disabled URL/object ingestion or incompatible upload-only mode.

## Accessibility Checklist

- [x] Native labels for dataset/source controls
- [x] Native radio controls for execution endpoint
- [x] Keyboard-accessible advanced settings
- [x] Visible focus treatment from shared controls
- [x] Semantic status colors with accompanying text

## Verification

- [x] 1848×910, 1600×900, 1024×768
- [x] Ocean light and dark themes
- [x] Local file selection and file ledger
- [x] Execution endpoint updates pipeline and CTA
- [x] Advanced settings disclosure
- [x] URL-source blocking state
- [x] Existing execution-monitor navigation
- [x] Vitest, TypeScript, ESLint, UI checks and `git diff --check`
- [x] Seven rendered operation-page behavior scenarios

## Design Tokens

- Existing `background`, `foreground`, `border`, `muted`, `info`, `success`, and `warning` tokens only
- 12px page gutter, 1680px maximum content width
- Shared 19px page title and 12px page description
- Rounded corners and subtle shadows limited to real controls
