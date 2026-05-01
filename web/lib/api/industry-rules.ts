import { apiClient } from '@/lib/api/core'

export type IndustryRulesetSummary = {
  name: string
  glossary_count: number
  pattern_count: number
  intent_count: number
}

export type IndustryRulesetDetail = IndustryRulesetSummary & {
  glossary: Record<string, string[]>
  patterns: Array<Record<string, any>>
  intents: Array<Record<string, any>>
}

export type IndustryRulesetListResponse = {
  schema: string
  count: number
  rulesets: IndustryRulesetSummary[]
}

export type IndustryRulesetDetailResponse = {
  schema: string
  ruleset: IndustryRulesetDetail
}

export type IndustryRulesUpdateResponse = {
  schema: string
  [key: string]: any
}

export type IndustryRulesGlossaryUpdateRequest = {
  glossary: Record<string, string[]>
}

export type IndustryRulesPatternsUpdateRequest = {
  patterns: Array<Record<string, any>>
}

export type IndustryRulesIntentsUpdateRequest = {
  intents: Array<Record<string, any>>
}

export type IndustryRulesRewritePreviewRequest = {
  ruleset: string
  query: string
}

export type IndustryRulesRewritePreviewResponse = {
  schema: string
  ruleset: string
  original_query: string
  expanded_query: string
  changed: boolean
}

export const industryRulesApi = {
  async listRulesets(): Promise<IndustryRulesetListResponse> {
    const { data } = await apiClient.get('/industry-rules/rulesets')
    return data
  },

  async getRuleset(name: string): Promise<IndustryRulesetDetailResponse> {
    const { data } = await apiClient.get(`/industry-rules/rulesets/${encodeURIComponent(name)}`)
    return data
  },

  async updateGlossary(
    name: string,
    body: IndustryRulesGlossaryUpdateRequest
  ): Promise<IndustryRulesUpdateResponse> {
    const { data } = await apiClient.put(`/industry-rules/rulesets/${encodeURIComponent(name)}/glossary`, body)
    return data
  },

  async updatePatterns(
    name: string,
    body: IndustryRulesPatternsUpdateRequest
  ): Promise<IndustryRulesUpdateResponse> {
    const { data } = await apiClient.put(`/industry-rules/rulesets/${encodeURIComponent(name)}/patterns`, body)
    return data
  },

  async updateIntents(
    name: string,
    body: IndustryRulesIntentsUpdateRequest
  ): Promise<IndustryRulesUpdateResponse> {
    const { data } = await apiClient.put(`/industry-rules/rulesets/${encodeURIComponent(name)}/intents`, body)
    return data
  },

  async previewRewrite(body: IndustryRulesRewritePreviewRequest): Promise<IndustryRulesRewritePreviewResponse> {
    const { data } = await apiClient.post('/industry-rules/preview-rewrite', body)
    return data
  },
}
