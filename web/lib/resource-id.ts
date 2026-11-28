import { z } from 'zod'

const uuidSchema = z.guid()
const compactUuidPattern = /^([0-9a-f]{8})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{4})([0-9a-f]{12})$/

export function normalizeResourceId(id: string): string {
  const lowercase = id.toLowerCase()
  let uuid = lowercase
  if (id.startsWith('urn:uuid:')) {
    uuid = lowercase.slice('urn:uuid:'.length)
  } else if (id.startsWith('{') && id.endsWith('}')) {
    uuid = lowercase.slice(1, -1)
  }
  if (uuidSchema.safeParse(uuid).success) return uuid

  const compactUuid = compactUuidPattern.exec(lowercase)
  return compactUuid === null ? id : compactUuid.slice(1).join('-')
}

export function matchesResourceId(returnedId: string | null | undefined, requestedId: string): boolean {
  if (returnedId === null || returnedId === undefined) return false
  if (returnedId === requestedId) return true
  if (!uuidSchema.safeParse(returnedId).success) return false

  return returnedId.toLowerCase() === normalizeResourceId(requestedId)
}
