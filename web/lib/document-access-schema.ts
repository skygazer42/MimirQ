import { z } from 'zod'
import type { DocumentAccessInfo } from '@/types/documents'

export const documentAccessModeSchema = z.enum(['inherit', 'only_me', 'all_team_members', 'partial_members'])

export const documentAccessInfoSchema = z.object({
  mode: documentAccessModeSchema,
  owner_id: z.string().nullish(),
  partial_member_list: z.array(z.string()).nullish(),
  partial_group_list: z.array(z.string()).nullish(),
}) satisfies z.ZodType<DocumentAccessInfo>
