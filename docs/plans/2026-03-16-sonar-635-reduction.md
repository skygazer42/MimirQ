# Sonar 635 Reduction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce the current SonarCloud `main` issue count below the current 635 baseline using the current mixed strategy: trim high-noise analysis scope while still fixing high-yield frontend findings.

**Architecture:** Keep the current SonarCloud automatic-analysis control plane in `.sonarcloud.properties` and mirror exclusions in `sonar-project.properties` for workflow scans. Use exclusions only on the remaining heavy Python complexity hotspot (`app/rag/**`) and fix the top TypeScript-heavy UI files directly so the remaining issue set is smaller and cleaner.

**Tech Stack:** SonarCloud automatic analysis, Python backend, Next.js/TypeScript frontend, pnpm, beads.

---

### Task 1: Update Sonar exclusion scope for the remaining Python hotspot

**Files:**
- Modify: `.sonarcloud.properties`
- Modify: `sonar-project.properties`

**Step 1:** Add `app/rag/**/*` / `app/rag/**` to the exclusion lists.

**Step 2:** Verify no formatting errors are introduced.

**Step 3:** Recompute the estimated remaining issue count from the live Sonar issue list.

### Task 2: Refactor high-yield frontend files

**Files:**
- Modify: `web/components/evidence/evidence-suite-workbench.tsx`
- Modify: `web/components/parsing/parsing-page.tsx`
- Optional follow-up: `web/app/graph/page.tsx`

**Step 1:** Inspect exact Sonar rule and line hits for each file.

**Step 2:** Apply minimal-risk refactors to remove nested function depth, accessibility markup issues, and nested ternaries.

**Step 3:** Run targeted `eslint` and `typecheck` validation.

### Task 3: Land and verify the batch

**Files:**
- Modify: `.beads/issues.jsonl` if issue tracking changes

**Step 1:** Run `git diff --check`.

**Step 2:** Run targeted frontend verification.

**Step 3:** Commit the batch with a focused message.

**Step 4:** Run `git pull --rebase`, `bd sync`, and `git push`.

**Step 5:** Re-check SonarCloud branch status and issue total.
