/**
 * Document-related types re-exported by `@/types`.
 */

import type { OpenApiSchema } from './backend'

export type {
  Document,
  DocumentList,
  GovernanceInfo,
  DocumentStatus,
  IngestDeadLetterItem,
  IngestDeadLetterList,
  IngestDeadLetterReplayResponse,
  DocumentTimelineItem,
  DocumentTimelineResponse,
  DocumentVersionInfo,
  DocumentVersionList,
  DocumentVersionDiff,
  DocumentAccessInfo,
  DocumentAccessUpdateRequest,
  DocumentFolderNode,
  DocumentFolderTreeResponse,
} from './backend'

export type DocumentHealthCard = OpenApiSchema<'DocumentHealthCard'>
