import { z } from 'zod'

import { dateTimeSchema } from '@/lib/response-schema'
import type { AuthResponse, AuthToken, UserProfile } from '@/types/backend'

export function readOidcExpiresIn(value: unknown): number | null {
  if (value === undefined) return 3600
  const seconds = typeof value === 'string' && value.trim() !== '' ? Number(value) : value
  return typeof seconds === 'number' && Number.isFinite(seconds) && seconds >= 0 ? seconds : null
}

export const authTokenSchema = z.object({
  access_token: z.string().trim().min(1),
  token_type: z.string().min(1),
  expires_in: z.number(),
}) satisfies z.ZodType<AuthToken>

const userProfileSchema = z.looseObject({
  id: z.string().min(1),
  username: z.string(),
  email: z.string(),
  is_active: z.boolean(),
  created_at: dateTimeSchema,
  last_login_at: dateTimeSchema.nullish(),
}) satisfies z.ZodType<UserProfile>

export const authResponseSchema = z.looseObject({
  user: userProfileSchema,
  token: authTokenSchema,
}) satisfies z.ZodType<AuthResponse>
