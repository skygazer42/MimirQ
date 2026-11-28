import { describe, expect, it } from 'vitest'

import type { ChunkPreviewFileItem } from './types'
import { createFileWorkspace, mergeScopedFiles, selectWorkspaceFile } from './file-workspace'

function file(id: string, revision = id): ChunkPreviewFileItem {
  return {
    id,
    fileRevision: revision,
    file: new File([id], `${id}.md`),
    displayName: `${id}.md`,
    source: 'parsing_workspace',
    documentId: id,
  }
}

describe('owned file collection and selection', () => {
  it('retains the actual current identity when an earlier unselected item disappears', () => {
    const a = file('a')
    const b = file('b')
    const c = file('c')
    const workspace = createFileWorkspace([a, b, c], b.id, new Set())
    Object.freeze(workspace.files)
    Object.freeze(workspace)

    const result = mergeScopedFiles(workspace, [b, c], '')

    expect(result.currentFileId).toBe('b')
    expect(result.files).toEqual([b, c])
    expect(workspace.files).toEqual([a, b, c])
    expect(selectWorkspaceFile(result, 'b')).toBe(result)
  })

  it('retains loaded current and selected inputs outside a bounded page, while applying matching revisions', () => {
    const a = file('a')
    const b = file('b')
    const c = file('c')
    const selected = new Set(['a'])
    const workspace = createFileWorkspace([a, b, c], 'b', selected)
    const nextB = file('b', 'second revision')

    const result = mergeScopedFiles(workspace, [nextB], '')

    expect(result.files).toEqual([a, nextB])
    expect(result.currentFileId).toBe('b')
    expect([...result.selectedIngestFileIds]).toEqual(['a'])
    expect([...selected]).toEqual(['a'])
    expect(workspace.files[1]).toBe(b)
  })

  it('uses opaque document identities and retains only selections belonging to the actual collection', () => {
    const source = file('__proto__')
    const workspace = createFileWorkspace([source], source.id, new Set([source.id, 'missing']))

    expect([...workspace.selectedIngestFileIds]).toEqual(['__proto__'])
    expect(selectWorkspaceFile(workspace, 'missing')).toBe(workspace)
    const replacement = file('__proto__', 'updated revision')
    expect(mergeScopedFiles(workspace, [replacement], '').files).toEqual([replacement])
    expect(createFileWorkspace([], null, workspace.selectedIngestFileIds).currentFileId).toBeNull()
  })
})
