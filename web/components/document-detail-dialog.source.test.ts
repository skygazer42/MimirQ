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
    const src = fs.readFileSync(path.resolve(__dirname, 'document-detail-dialog.tsx'), 'utf8')

    expect(src).toContain('useActionState')
    expect(src).toContain('useOptimistic')
    expect(src).toContain('useFormStatus')
    expect(src).toContain('function DocumentTagsSaveButton')
    expect(src).toContain('const { pending } = useFormStatus()')
    expect(src).toContain('const [optimisticTags, applyOptimisticTags] = useOptimistic(')
    expect(src).toContain('const [, saveTagsAction, isSavingTags] = useActionState(')
    expect(src).toContain('startTransition(() => {')
    expect(src).toContain('applyOptimisticTags(nextTags)')
    expect(src).toContain('<form action={saveTagsAction}')
    expect(src).not.toContain('setIsSavingTags(true)')
    expect(src).not.toContain('setIsSavingTags(false)')
  })

  it('uses React actions for access-control and lifecycle form submissions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-detail-dialog.tsx'), 'utf8')

    expect(src).toContain('const [, saveAccessAction, isSavingAccess] = useActionState(')
    expect(src).toContain('const [, saveLifecycleAction, isSavingLifecycle] = useActionState(')
    expect(src).toContain('action={saveAccessAction}')
    expect(src).toContain('<form action={saveLifecycleAction}')
    expect(src).toContain('function DocumentLifecycleSaveButton')
    expect(src).not.toContain('setIsSavingAccess(true)')
    expect(src).not.toContain('setIsSavingAccess(false)')
    expect(src).not.toContain('setIsSavingLifecycle(true)')
    expect(src).not.toContain('setIsSavingLifecycle(false)')
  })
})
