import { apiClient } from '@/lib/api/core'
import type {
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
