import type { ChunkPreviewFileItem } from './types'

export type FileWorkspaceState = Readonly<{
  files: ChunkPreviewFileItem[]
  currentFileId: string | null
  selectedIngestFileIds: ReadonlySet<string>
}>

export function createFileWorkspace(
  files: ChunkPreviewFileItem[],
  currentFileId: string | null,
  selectedIngestFileIds: ReadonlySet<string>,
): FileWorkspaceState {
  const ids = new Set(files.map((file) => file.id))
  return {
    files,
    currentFileId: currentFileId !== null && ids.has(currentFileId) ? currentFileId : (files[0]?.id ?? null),
    selectedIngestFileIds: new Set([...selectedIngestFileIds].filter((id) => ids.has(id))),
  }
}

export function selectWorkspaceFile(workspace: FileWorkspaceState, id: string): FileWorkspaceState {
  if (workspace.currentFileId === id || !workspace.files.some((file) => file.id === id)) return workspace
  return { ...workspace, currentFileId: id }
}

function isManualChunkFile(item: Pick<ChunkPreviewFileItem, 'source'>): boolean {
  return item.source === 'local_upload' || item.source === 'example'
}

export function isChunkPreviewFileInScope(
  item: Pick<ChunkPreviewFileItem, 'source' | 'datasetId'>,
  datasetId: string,
): boolean {
  const scope = datasetId.trim()
  if (isManualChunkFile(item)) {
    const sourceDatasetId = item.datasetId?.trim()
    return scope.length > 0 ? sourceDatasetId === scope : !sourceDatasetId
  }
  return scope.length === 0
    ? item.source === 'parsing_workspace'
    : item.source === 'knowledge_base' && item.datasetId === scope
}

export function mergeScopedFiles(
  workspace: FileWorkspaceState,
  scoped: readonly ChunkPreviewFileItem[],
  datasetId: string,
): FileWorkspaceState {
  const incoming = new Map<string, ChunkPreviewFileItem>()
  for (const file of scoped) {
    if (!incoming.has(file.id)) incoming.set(file.id, file)
  }
  const merged = new Map<string, ChunkPreviewFileItem>()
  for (const file of workspace.files) {
    const replacement = incoming.get(file.id)
    if (replacement !== undefined) merged.set(file.id, replacement)
    else if (
      isChunkPreviewFileInScope(file, datasetId) &&
      (isManualChunkFile(file) || file.id === workspace.currentFileId || workspace.selectedIngestFileIds.has(file.id))
    ) {
      // A loaded current/selected input remains usable outside a bounded remote page.
      merged.set(file.id, file)
    }
  }
  for (const [key, file] of incoming) if (!merged.has(key)) merged.set(key, file)
  return createFileWorkspace([...merged.values()], workspace.currentFileId, workspace.selectedIngestFileIds)
}
