import { z } from 'zod'
import type { AxiosResponse } from 'axios'

import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import { integerSchema, recordSchema } from '@/lib/response-schema'
import { parseApiResponse } from '@/lib/openapi-request'
import type {
  IndustryRulesetListResponse,
  IndustryRulesetDetailResponse,
  IndustryRulesUpdateResponse,
  IndustryRulesGlossaryUpdateRequest,
  IndustryRulesPatternsUpdateRequest,
  IndustryRulesIntentsUpdateRequest,
  IndustryRulesRewritePreviewRequest,
  IndustryRulesRewritePreviewResponse,
} from '@/types/backend'

const glossarySchema = z.custom<Record<string, string[]>>((value) => {
  const glossary = recordSchema.safeParse(value)
  return (
    glossary.success &&
    Object.values(glossary.data).every(
      (words) => Array.isArray(words) && words.every((word) => typeof word === 'string'),
    )
  )
})

const rulesetSummarySchema = z.object({
  name: z.string(),
  glossary_count: integerSchema,
  pattern_count: integerSchema,
  intent_count: integerSchema,
})

const rulesetListSchema = z.object({
  schema: z.string(),
  count: integerSchema,
  rulesets: z.array(rulesetSummarySchema),
}) satisfies z.ZodType<IndustryRulesetListResponse>

const rulesetDetailSchema = z.object({
  schema: z.string(),
  ruleset: rulesetSummarySchema.extend({
    glossary: glossarySchema,
    patterns: z.array(recordSchema),
    intents: z.array(recordSchema),
  }),
}) satisfies z.ZodType<IndustryRulesetDetailResponse>

const rewritePreviewSchema = z.object({
  schema: z.string(),
  ruleset: z.string(),
  original_query: z.string(),
  expanded_query: z.string(),
  changed: z.boolean(),
}) satisfies z.ZodType<IndustryRulesRewritePreviewResponse>

const rulesetUpdateSchema = z.object({
  schema: z.string(),
  ruleset: z.string(),
  section: z.enum(['glossary', 'patterns', 'intents']),
  updated_count: integerSchema.nonnegative(),
}) satisfies z.ZodType<IndustryRulesUpdateResponse>

function parseRulesetUpdate(
  response: AxiosResponse<unknown>,
  name: string,
  section: z.infer<typeof rulesetUpdateSchema>['section'],
): IndustryRulesUpdateResponse {
  const receipt = parseApiResponse(response, rulesetUpdateSchema, 'IndustryRulesUpdateResponse')
  if (receipt.ruleset !== name.trim() || receipt.section !== section) {
    throw new Error('行业规则更新回执与提交目标不一致，请先重新读取规则集')
  }
  return receipt
}

// Re-exported from generated OpenAPI types (see web/types/backend.ts) so existing
// imports from '@/lib/api/industry-rules' keep working without hand-written duplicates.
export type {
  IndustryRulesetSummary,
  IndustryRulesetDetail,
  IndustryRulesetListResponse,
  IndustryRulesetDetailResponse,
  IndustryRulesUpdateResponse,
  IndustryRulesGlossaryUpdateRequest,
  IndustryRulesPatternsUpdateRequest,
  IndustryRulesIntentsUpdateRequest,
  IndustryRulesRewritePreviewRequest,
  IndustryRulesRewritePreviewResponse,
} from '@/types/backend'

export const industryRulesApi = {
  async listRulesets(options?: ApiRequestOptions): Promise<IndustryRulesetListResponse> {
    const response = await apiClient.get<unknown>('/industry-rules/rulesets', {
      signal: options?.signal,
    })
    return parseApiResponse(response, rulesetListSchema, 'IndustryRulesetListResponse')
  },

  async getRuleset(name: string, options?: ApiRequestOptions) {
    const response = await apiClient.get<unknown>(`/industry-rules/rulesets/${encodeURIComponent(name)}`, {
      signal: options?.signal,
    })
    const detail = parseApiResponse(response, rulesetDetailSchema, 'IndustryRulesetDetailResponse')
    if (detail.ruleset.name !== name.trim()) throw new Error('返回的规则集与请求不一致。')
    return detail
  },

  async updateGlossary(name: string, body: IndustryRulesGlossaryUpdateRequest): Promise<IndustryRulesUpdateResponse> {
    const response = await apiClient.put<unknown>(`/industry-rules/rulesets/${encodeURIComponent(name)}/glossary`, body)
    return parseRulesetUpdate(response, name, 'glossary')
  },

  async updatePatterns(name: string, body: IndustryRulesPatternsUpdateRequest): Promise<IndustryRulesUpdateResponse> {
    const response = await apiClient.put<unknown>(`/industry-rules/rulesets/${encodeURIComponent(name)}/patterns`, body)
    return parseRulesetUpdate(response, name, 'patterns')
  },

  async updateIntents(name: string, body: IndustryRulesIntentsUpdateRequest): Promise<IndustryRulesUpdateResponse> {
    const response = await apiClient.put<unknown>(`/industry-rules/rulesets/${encodeURIComponent(name)}/intents`, body)
    return parseRulesetUpdate(response, name, 'intents')
  },

  async previewRewrite(
    body: IndustryRulesRewritePreviewRequest,
    options?: ApiRequestOptions,
  ): Promise<IndustryRulesRewritePreviewResponse> {
    const response = await apiClient.post<unknown>('/industry-rules/preview-rewrite', body, {
      signal: options?.signal,
    })
    return parseApiResponse(response, rewritePreviewSchema, 'IndustryRulesRewritePreviewResponse')
  },
}
