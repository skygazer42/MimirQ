# 2026-03-30 next-intl nav slice rollout

## Goal
- move the navigation-specific copy (breadcrumbs, slash menu, knowledge import menu, document viewer actions) onto dedicated next-intl namespaces so the nav shell rolls out with localized messages.

## Checklist
1. Define the nav slice plan and owned namespaces (`Breadcrumb`, `SlashMenu`, `KnowledgeImportMenu`, `DocumentViewerActions`).
2. Update each owned component to read user-visible strings through `useTranslations` and wire the new namespaces.
3. Add source tests that assert the components pull copy from the catalog, not hardcoded literals.
4. Populate `web/i18n/messages/zh-CN.ts` with the new namespace entries needed for this slice.
5. From `web`, run the focused vitest and eslint commands listed in the requirements to verify the slice.
6. Commit the changes with a focused message and push `parallel-next-intl-msg-nav` to origin.
