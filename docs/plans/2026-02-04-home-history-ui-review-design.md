# Home + History UI Review (Design Notes)

**Date:** 2026-02-04

## Goal

Improve first-impression clarity and reduce interaction ambiguity on:
- `http://localhost:3000/` (welcome/empty chat state)
- `http://localhost:3000/history` (empty state + primary CTA)

## Direction (Interface Design)

**User intent:** “Ask a question” should be the single obvious primary action. Everything else (templates, RAG params, memory toggles) is supportive, not competing.

**Feel:** Calm, precise, B2B tool. Composer-first. Subtle depth (token shadows), no decorative gradients.

**Signature:** A “composer that feels like a device”: a single, generous input surface with integrated controls; prompt starters behave like “quick fills”, not a separate onboarding flow.

**Rejecting defaults:**
- No redundant “Start” CTA when the composer is already present.
- No floating chips/pills above the composer that look like tags; settings must feel attached to the input surface.
- Empty states must not just say “nothing here”; they must offer one clear next action.

## Key UX Decisions

1. **Welcome state**
   - Remove the redundant “开始提问” button.
   - Convert feature cards into **prompt starters**:
     - Click fills the composer (does not auto-send).
     - Clear affordance via hover/focus states.

2. **Composer settings**
   - Move the `RAG 配置` trigger **inside** the composer surface (not floating above it).
   - Keep the existing Popover content (retrieval mode, thresholds, memory, structured output) unchanged.

3. **History empty state**
   - When no conversation is selected (or none exist), show a centered empty state with a primary CTA: **“发起新对话”**.
   - Make the page-level “新建对话” action visually primary.

## Constraints / Baseline UI

- Tailwind tokens first; no new random hex values.
- Motion only where necessary; respect `prefers-reduced-motion`.
- Empty states always include one clear next action.

