# Frontend UI Polish (Round 5) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Execute 20 small, reviewable tasks (1 task = 1 commit) to improve global UI consistency (A) and reduce motion/performance overhead (C), aligned with `baseline-ui` constraints (token-first, no glows/gradients by default, minimal motion, avoid layout animation).

**Scope:** Next.js App Router UI (Tailwind + Radix primitives). This round focuses on:
- removing `transition-all` hotspots (especially ones that may animate layout)
- calming glow-heavy UI (shadows/backdrop blur) on high-frequency surfaces
- switching small progress animations from `width` to `transform: scaleX`
- simplifying multi-accent dropdown palettes to semantic tokens
- keeping frontend/backend API contract checks green (OpenAPI + contract/coverage)

---

## Task 1: Add design doc for round 5

**Files:**
- Create: `docs/plans/2026-02-02-frontend-ui-polish-round-5-design.md`

**Commit:**
```bash
git add docs/plans/2026-02-02-frontend-ui-polish-round-5-design.md
git commit -m "docs(plans): add frontend UI polish round 5 design"
```

---

## Task 2: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-02-frontend-ui-polish-round-5.md`

**Commit:**
```bash
git add docs/plans/2026-02-02-frontend-ui-polish-round-5.md
git commit -m "docs(plans): add frontend UI polish round 5 plan"
```

---

## Task 3: DataGovernancePanel: empty state remove glow + reduce motion

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Steps:**
1. Remove `shadow-[...]` glow and `scale-[...]` from the drag/drop empty state.
2. Replace sky palette usage in that section with `primary`/token classes.
3. Keep motion minimal; no new animation.
4. Verify lint + typecheck.
5. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "style(governance): calm empty state visuals (no glow)"
```

---

## Task 4: DataGovernancePanel: control focus rings + remove transition-all

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Steps:**
1. Replace `focus:ring-sky-*` and similar palette rings with token rings / `focus-ring`.
2. Replace `transition-all` on input/select controls with narrower transitions and <=200ms.
3. Verify lint + typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "style(governance): tighten control focus + transitions"
```

---

## Task 5: DataGovernancePanel: resizer handles + floating buttons transition hygiene

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Steps:**
1. Replace `transition-all` on resizer handles and floating buttons with `transition-opacity` / `transition-colors`.
2. Replace `sky-*` active/hover colors on handles with token equivalents.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "perf(governance): tighten resizer/overlay transitions"
```

---

## Task 6: ModelProviderCard: remove hover translate + tighten transitions

**Files:**
- Modify: `web/components/model-provider-card.tsx`

**Steps:**
1. Remove hover translate motion; keep feedback via shadow/border only.
2. Replace `transition-all` with narrower transitions and <=200ms.
3. Verify lint + typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/model-provider-card.tsx
git commit -m "style(models): tighten provider card interactions"
```

---

## Task 7: TabsTrigger: remove transition-all

**Files:**
- Modify: `web/components/ui/tabs.tsx`

**Steps:**
1. Replace `transition-all` with `transition-colors` (and duration <=200ms).
2. Add `motion-reduce` guard.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/tabs.tsx
git commit -m "style(ui): tighten TabsTrigger transitions"
```

---

## Task 8: ModeToggle: narrow transitions to transform only

**Files:**
- Modify: `web/components/mode-toggle.tsx`

**Steps:**
1. Replace `transition-all` on icons with `transition-transform`.
2. Ensure duration <=200ms and add `motion-reduce` guard.
3. Verify lint.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint
```

**Commit:**
```bash
git add web/components/mode-toggle.tsx
git commit -m "style(theme): tighten mode toggle icon transitions"
```

---

## Task 9: StatCard: replace transition-all

**Files:**
- Modify: `web/components/ui/stats-card.tsx`

**Steps:**
1. Replace `transition-all` with `transition-shadow`/`transition-colors` (<=200ms).
2. Prefer `size-*` for square icons where possible.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/stats-card.tsx
git commit -m "style(ui): tighten StatCard hover transitions"
```

---

## Task 10: TaskCenter: polish floating trigger (no rotate / safe-area / tokens)

**Files:**
- Modify: `web/components/task-center.tsx`

**Steps:**
1. Replace `h-12 w-12` with `size-12`.
2. Remove hover rotate and `transition-all`; keep subtle <=200ms feedback.
3. Replace ping dot `sky-*` with token classes (primary).
4. Respect safe-area insets.
5. Verify lint + typecheck.
6. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/task-center.tsx
git commit -m "style(tasks): polish task center trigger"
```

---

## Task 11: Chat message bubble: reduce glow + remove transition-all

**Files:**
- Modify: `web/components/chat/message-item.tsx`

**Steps:**
1. Replace message container `transition-all` with narrower transitions.
2. Remove glow-heavy shadows / backdrop blur from user bubble.
3. Keep surfaces token-driven and calm.
4. Verify lint + typecheck.
5. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/chat/message-item.tsx
git commit -m "style(chat): calm message bubble surfaces"
```

---

## Task 12: Chat message steps: remove always-on looping indicators

**Files:**
- Modify: `web/components/chat/message-item.tsx`

**Steps:**
1. Remove `animate-ping`/`animate-pulse` loops in the steps header/list.
2. Keep a static status indicator and readable typography.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/chat/message-item.tsx
git commit -m "perf(chat): remove looping step indicators"
```

---

## Task 13: DocumentViewerPanel: remove transition-all on width changes

**Files:**
- Modify: `web/components/document-viewer-panel.tsx`

**Steps:**
1. Remove `transition-all` from the right panel container to avoid animating `width`.
2. Keep the rest of styling unchanged.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/document-viewer-panel.tsx
git commit -m "perf(viewer): avoid layout animation on panel width"
```

---

## Task 14: FileQueueItem: progress bar scaleX (no width transition)

**Files:**
- Modify: `web/components/ui/file-queue-item.tsx`

**Steps:**
1. Replace progress bar `width` transition with `transform: scaleX`.
2. Replace `bg-sky-500` with `bg-primary`.
3. Verify lint + typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/file-queue-item.tsx
git commit -m "perf(ui): make file queue progress compositor-only"
```

---

## Task 15: FileQueueItem: tighten card transitions + tokenise status accents

**Files:**
- Modify: `web/components/ui/file-queue-item.tsx`

**Steps:**
1. Replace card `transition-all` with narrower transitions and <=200ms.
2. Replace status accent palette (`sky/slate/red`) with semantic tokens where practical.
3. Ensure icon-only buttons remain accessible.
4. Verify lint + typecheck.
5. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/file-queue-item.tsx
git commit -m "style(ui): tighten file queue item surfaces"
```

---

## Task 16: ParserDropdown: simplify palette to semantic tokens

**Files:**
- Modify: `web/components/ui/parser-dropdown.tsx`

**Steps:**
1. Replace multi-color `COLOR_MAP` (purple/fuchsia/etc.) with semantic tokens.
2. Replace `transition-all` on trigger and rows with narrower transitions.
3. Verify lint + typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/parser-dropdown.tsx
git commit -m "style(ui): simplify parser dropdown accents"
```

---

## Task 17: ChunkStrategyDropdown: simplify palette to semantic tokens

**Files:**
- Modify: `web/components/ui/chunk-strategy-dropdown.tsx`

**Steps:**
1. Replace multi-color `COLOR_MAP` with semantic tokens (primary/success/warning/info/muted).
2. Replace `transition-all` on trigger and rows with narrower transitions.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/chunk-strategy-dropdown.tsx
git commit -m "style(ui): simplify chunk strategy dropdown accents"
```

---

## Task 18: DataClassifier: replace transition-all on selection cards

**Files:**
- Modify: `web/components/data-governance/data-classifier.tsx`

**Steps:**
1. Replace `transition-all` with `transition-colors` and <=200ms.
2. Add `motion-reduce` guard.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/data-governance/data-classifier.tsx
git commit -m "style(governance): tighten classifier selection transitions"
```

---

## Task 19: DataAnnotator: replace transition-all on type cards

**Files:**
- Modify: `web/components/data-governance/data-annotator.tsx`

**Steps:**
1. Replace `transition-all` with `transition-colors` and <=200ms.
2. Add `motion-reduce` guard.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/data-governance/data-annotator.tsx
git commit -m "style(governance): tighten annotator type transitions"
```

---

## Task 20: Verification record for round 5

**Files:**
- Create: `docs/plans/2026-02-02-frontend-ui-polish-round-5-verification.md`

**Steps:**
1. Run `make openapi-check` and `make enterprise-checks`.
2. Record the commands + outcomes in a short verification doc.
3. Commit.

**Verify:**
```bash
make openapi-check
make enterprise-checks
```

**Commit:**
```bash
git add docs/plans/2026-02-02-frontend-ui-polish-round-5-verification.md
git commit -m "docs(plans): record round 5 verification"
```

