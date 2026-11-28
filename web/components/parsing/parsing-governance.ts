import type { ParsedFileData } from '@/store/use-parsed-files-store'

import type { ParsedFile } from './parsing-types'

export type ParsingGovernanceTarget =
  | { kind: 'queue'; file: ParsedFile; selectionId: string }
  | { kind: 'library'; file: ParsedFileData; selectionId: string }

export function getParsingGovernanceTargets(
  files: ParsedFile[],
  libraryFiles: ParsedFileData[],
  datasetId: string | null,
): ParsingGovernanceTarget[] {
  const scopedQueue = datasetId === null ? files : files.filter((file) => file.datasetId === datasetId)
  const queueLibraryIds = new Set(scopedQueue.map((file) => file.libraryId))
  const queueTargets = scopedQueue
    .filter((file) => file.status === 'parsed' && file.governanceStatus === 'ready')
    .map((file) => ({ kind: 'queue' as const, file, selectionId: file.libraryId ?? file.id }))
  const libraryTargets = libraryFiles
    .filter(
      (file) =>
        !queueLibraryIds.has(file.id) &&
        file.governanceStatus === 'ready' &&
        (file.status ?? 'parsed') === 'parsed' &&
        (datasetId === null ||
          ((file.source === 'knowledge_base' || file.source === 'parsing_workspace') && file.datasetId === datasetId)),
    )
    .map((file) => ({ kind: 'library' as const, file, selectionId: file.id }))
  return [...queueTargets, ...libraryTargets]
}
