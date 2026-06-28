import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document detail dialog source', () => {
  it('extracts versions and access dialogs into dedicated submodules', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-detail-dialog.tsx'), 'utf8')

    expect(src).toContain("from '@/components/document-detail-dialog/document-access-dialog'")
    expect(src).toContain("from '@/components/document-detail-dialog/document-versions-dialog'")
    expect(src).toContain('<DocumentVersionsDialog')
    expect(src).toContain('<DocumentAccessDialog')
    expect(fs.existsSync(path.resolve(__dirname, 'document-detail-dialog/document-access-dialog.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'document-detail-dialog/document-versions-dialog.tsx'))).toBe(true)
  })

  it('uses React actions and optimistic state for document tag edits', () => {
    const mainSrc = fs.readFileSync(path.resolve(__dirname, 'document-detail-dialog.tsx'), 'utf8')
    const tagsPanelSrc = fs.readFileSync(
      path.resolve(__dirname, 'document-detail-dialog/document-detail-tags-panel.tsx'),
      'utf8'
    )

    expect(mainSrc).toContain('useActionState')
    expect(mainSrc).toContain('useOptimistic')
    expect(mainSrc).toContain('useFormStatus')
    expect(mainSrc).toContain('function DocumentSaveButton')
    expect(mainSrc).toContain('const { pending } = useFormStatus()')
    expect(mainSrc).toContain('const [optimisticTags, applyOptimisticTags] = useOptimistic(')
    expect(mainSrc).toContain('const [, saveTagsAction, isSavingTags] = useActionState(')
    expect(mainSrc).toContain('startTransition(() => {')
    expect(mainSrc).toContain('applyOptimisticTags(nextTags)')
    expect(tagsPanelSrc).toContain('<form action={saveAction}')
    expect(tagsPanelSrc).toContain('{saveButton}')
    expect(mainSrc).not.toContain('setIsSavingTags(true)')
    expect(mainSrc).not.toContain('setIsSavingTags(false)')
  })

  it('uses React actions for access-control and lifecycle form submissions', () => {
    const mainSrc = fs.readFileSync(path.resolve(__dirname, 'document-detail-dialog.tsx'), 'utf8')
    const accessDialogSrc = fs.readFileSync(
      path.resolve(__dirname, 'document-detail-dialog/document-access-dialog.tsx'),
      'utf8'
    )
    const lifecyclePanelSrc = fs.readFileSync(
      path.resolve(__dirname, 'document-detail-dialog/document-detail-lifecycle-panel.tsx'),
      'utf8'
    )

    expect(mainSrc).toContain('const [, saveAccessAction, isSavingAccess] = useActionState(')
    expect(mainSrc).toContain('const [, saveLifecycleAction, isSavingLifecycle] = useActionState(')
    expect(mainSrc).toContain('action={saveAccessAction}')
    expect(lifecyclePanelSrc).toContain('<form action={saveAction}')
    expect(lifecyclePanelSrc).toContain('{saveButton}')
    expect(accessDialogSrc).toContain('function DocumentAccessSaveButton()')
    expect(accessDialogSrc).toContain('<form action={action}>')
    expect(mainSrc).not.toContain('setIsSavingAccess(true)')
    expect(mainSrc).not.toContain('setIsSavingAccess(false)')
    expect(mainSrc).not.toContain('setIsSavingLifecycle(true)')
    expect(mainSrc).not.toContain('setIsSavingLifecycle(false)')
  })

  it('extracts the remaining detail surfaces into dedicated submodules to keep the main dialog manageable', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-detail-dialog.tsx'), 'utf8')
    const lineCount = src.split('\n').length

    expect(src).toContain("from '@/components/document-detail-dialog/document-detail-summary-cards'")
    expect(src).toContain("from '@/components/document-detail-dialog/document-detail-tags-panel'")
    expect(src).toContain("from '@/components/document-detail-dialog/document-detail-lifecycle-panel'")
    expect(src).toContain("from '@/components/document-detail-dialog/document-detail-activity-panel'")
    expect(src).toContain('<DocumentDetailSummaryCards')
    expect(src).toContain('<DocumentDetailTagsPanel')
    expect(src).toContain('<DocumentDetailLifecyclePanel')
    expect(src).toContain('<DocumentDetailActivityPanel')
    expect(lineCount).toBeLessThanOrEqual(1500)
    expect(fs.existsSync(path.resolve(__dirname, 'document-detail-dialog/document-detail-summary-cards.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'document-detail-dialog/document-detail-tags-panel.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'document-detail-dialog/document-detail-lifecycle-panel.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'document-detail-dialog/document-detail-activity-panel.tsx'))).toBe(true)
  })

  it('loads document detail, versions, and timeline through TanStack Query instead of hand-rolled loaders', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-detail-dialog.tsx'), 'utf8')

    expect(src).toContain('useQuery')
    expect(src).toContain('useQueryClient')
    expect(src).toContain('queryKeys.documents.detail')
    expect(src).toContain('queryKeys.documents.access')
    expect(src).toContain('queryKeys.documents.versions')
    expect(src).toContain('queryKeys.documents.timeline')
    expect(src).not.toContain('const loadDetail = useCallback')
    expect(src).not.toContain('const loadVersions = useCallback')
    expect(src).not.toContain('const loadTimeline = useCallback')
  })
})
