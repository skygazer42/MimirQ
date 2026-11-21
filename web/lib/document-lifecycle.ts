import { z } from 'zod'

import type { DocumentLifecycleMetadata, DocumentLifecycleMetadataUpdateRequest } from '@/types/processing'

export const publicationStatusSchema = z.enum(['draft', 'published', 'deprecated'])

export type LifecycleDraft = {
  publicationStatus: DocumentLifecycleMetadata['publication_status']
  owner: string
  reviewDueAt: string
  authorityLevel: string
  supersedesDocumentId: string
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function formatLifecycleDateTime(value: string | null | undefined): string {
  if (value === null || value === undefined) return ''
  const date = new Date(value)
  const pad = (part: number) => String(part).padStart(2, '0')
  const calendarDate = [date.getFullYear(), pad(date.getMonth() + 1), pad(date.getDate())].join('-')
  const clockTime = [pad(date.getHours()), pad(date.getMinutes()), pad(date.getSeconds())].join(':')
  const milliseconds = String(date.getMilliseconds()).padStart(3, '0')
  return `${calendarDate}T${clockTime}.${milliseconds}`
}

export function createLifecycleDraft(metadata: DocumentLifecycleMetadata): LifecycleDraft {
  return {
    publicationStatus: metadata.publication_status,
    owner: metadata.lifecycle_owner === null || metadata.lifecycle_owner === undefined ? '' : metadata.lifecycle_owner,
    reviewDueAt: formatLifecycleDateTime(metadata.review_due_at),
    authorityLevel:
      metadata.authority_level === null || metadata.authority_level === undefined
        ? ''
        : String(metadata.authority_level),
    supersedesDocumentId:
      metadata.supersedes_document_id === null || metadata.supersedes_document_id === undefined
        ? ''
        : metadata.supersedes_document_id,
  }
}

export function getLifecycleValidationKey(draft: LifecycleDraft) {
  const supersedes = draft.supersedesDocumentId.trim()
  if (supersedes.length > 0 && !UUID_PATTERN.test(supersedes)) return 'validation.supersedesUuid'
  const authority = draft.authorityLevel.trim()
  if (authority.length > 0) {
    const value = Number(authority)
    if (!Number.isInteger(value)) return 'validation.authorityInteger'
    if (value < 0 || value > 100) return 'validation.authorityRange'
  }
  const due = draft.reviewDueAt.trim()
  if (due.length > 0 && Number.isNaN(new Date(due).getTime())) return 'validation.reviewDueAt'
  return null
}

/** Call after validation. Unedited fields stay out of PATCH, including original time precision. */
export function buildLifecyclePatch(
  baseline: DocumentLifecycleMetadata,
  draft: LifecycleDraft,
): DocumentLifecycleMetadataUpdateRequest {
  const initial = createLifecycleDraft(baseline)
  const patch: DocumentLifecycleMetadataUpdateRequest = {}
  if (draft.publicationStatus !== initial.publicationStatus) patch.publication_status = draft.publicationStatus
  if (draft.owner !== initial.owner) {
    const owner = draft.owner.trim()
    patch.lifecycle_owner = owner.length === 0 ? null : owner
  }
  if (draft.authorityLevel !== initial.authorityLevel) {
    const authority = draft.authorityLevel.trim()
    patch.authority_level = authority.length === 0 ? null : Number(authority)
  }
  if (draft.reviewDueAt !== initial.reviewDueAt) {
    const due = draft.reviewDueAt.trim()
    patch.review_due_at = due.length === 0 ? null : new Date(due).toISOString()
  }
  if (draft.supersedesDocumentId !== initial.supersedesDocumentId) {
    const supersedes = draft.supersedesDocumentId.trim()
    patch.supersedes_document_id = supersedes.length === 0 ? null : supersedes
  }
  return patch
}
