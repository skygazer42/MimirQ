import type { JsonObject } from '@/types/common'
import type {
  KGHardcaseMode,
  KGSearchDiagnosticsItem,
  KGSearchDiagnosticsRequest,
  KGSearchDiagnosticsResponse,
  KGSearchDiagnosticsRunDetail,
  KGSearchDiagnosticsRunList,
  KGSearchDiagnosticsRunListParams,
  KGSearchDiagnosticsRunOut,
  RagasConversationReadinessItem,
  RagasConversationReadinessRequest,
  RagasConversationReadinessResponse,
  RagasItem,
  RagasRun,
  RagasRunCreateRequest,
  RagasRunDetail,
  RagasRunList,
  RagasRegressionRunDiffResponse,
  RegressionAblationBatchRequest,
  RegressionAblationBatchResponse,
  RegressionCase,
  RegressionCaseBundleV1,
  RegressionCaseCreate,
  RegressionCaseImportResponse,
  RegressionCaseList,
  RegressionCasePatch,
  RegressionRun,
  RegressionRunCreate,
  RegressionRunDetail,
  RegressionRunList,
  TestGenFromConversationsRequest,
  TestGenFromDocsRequest,
  TestGenResponse,
} from '@/types/evaluation'
import type { OpenApiSchema } from '@/types/backend'

import { apiClient } from '@/lib/api/core'

export type {
  KGHardcaseMode,
  KGSearchDiagnosticsItem,
  KGSearchDiagnosticsRequest,
  KGSearchDiagnosticsResponse,
  KGSearchDiagnosticsRunDetail,
  KGSearchDiagnosticsRunList,
  KGSearchDiagnosticsRunListParams,
  KGSearchDiagnosticsRunOut,
  RagasConversationReadinessItem,
  RagasConversationReadinessRequest,
  RagasConversationReadinessResponse,
  RagasItem,
  RagasRun,
  RagasRunCreateRequest,
  RagasRunDetail,
  RagasRunList,
} from '@/types/evaluation'

type SyntheticHardcaseGenerateResponse = OpenApiSchema<'SyntheticHardcaseGenerateResponse'>
type RegressionRunLeaderboardResponse = OpenApiSchema<'RagasRegressionRunLeaderboardResponse'>

export const evaluationApi = {
  async getRagasConversationReadiness(
    params: RagasConversationReadinessRequest,
  ): Promise<RagasConversationReadinessResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/conversation-readiness', params)
    return data
  },

  async createRagasRun(params: RagasRunCreateRequest): Promise<RagasRun> {
    const { data } = await apiClient.post('/evaluations/ragas/runs', params)
    return data
  },

  async listRagasRuns(params?: { skip?: number; limit?: number; conversation_id?: string }): Promise<RagasRunList> {
    const { data } = await apiClient.get('/evaluations/ragas/runs', { params })
    return data
  },

  async getRagasRun(
    runId: string,
    params?: { include_items?: boolean; include_contexts?: boolean },
  ): Promise<RagasRunDetail> {
    const { data } = await apiClient.get(`/evaluations/ragas/runs/${runId}`, { params })
    return data
  },

  async createRegressionCase(params: RegressionCaseCreate): Promise<RegressionCase> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/cases', params)
    return data
  },

  async listRegressionCases(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
  }): Promise<RegressionCaseList> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/cases', { params })
    return data
  },

  async exportRegressionCases(params: { dataset_id: string }): Promise<RegressionCaseBundleV1> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/cases/export', { params })
    return data as RegressionCaseBundleV1
  },

  async importRegressionCases(payload: {
    dataset_id: string
    overwrite?: boolean
    max_items?: number
    items: RegressionCaseBundleV1['items']
  }): Promise<RegressionCaseImportResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/cases/import', payload)
    return data as RegressionCaseImportResponse
  },

  async deleteRegressionCase(caseId: string): Promise<void> {
    await apiClient.delete(`/evaluations/ragas/regression/cases/${caseId}`)
  },

  async patchRegressionCase(caseId: string, payload: RegressionCasePatch): Promise<RegressionCase> {
    const { data } = await apiClient.patch(`/evaluations/ragas/regression/cases/${caseId}`, payload)
    return data
  },

  async generateSyntheticHardcases(payload: {
    dataset_id: string
    case_ids?: string[]
    max_cases?: number
    hardcases_per_case?: number
    max_created?: number
    dry_run?: boolean
    tag?: string
  }): Promise<SyntheticHardcaseGenerateResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/cases/synthetic-hardcases', payload)
    return data
  },

  async generateFromDocuments(params: TestGenFromDocsRequest): Promise<TestGenResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/test-gen/from-documents', params)
    return data
  },

  async generateFromConversations(params: TestGenFromConversationsRequest): Promise<TestGenResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/test-gen/from-conversations', params)
    return data
  },

  async createRegressionRun(params: RegressionRunCreate): Promise<RegressionRun> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/runs', params)
    return data
  },

  async createRegressionAblationBatch(
    params: RegressionAblationBatchRequest,
  ): Promise<RegressionAblationBatchResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/ablation/batch', params)
    return data
  },

  async listRegressionRuns(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
  }): Promise<RegressionRunList> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/runs', { params })
    return data
  },

  async getRegressionRunLeaderboard(params: {
    dataset_id: string
    metric_key?: string
    limit?: number
    include_incomplete?: boolean
    max_candidates?: number
  }): Promise<RegressionRunLeaderboardResponse> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/runs/leaderboard', { params })
    return data
  },

  async getRegressionRun(
    runId: string,
    params?: { include_items?: boolean; include_contexts?: boolean },
  ): Promise<RegressionRunDetail> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}`, { params })
    return data
  },

  async diffRegressionRuns(
    runId: string,
    params: {
      base_run_id: string
      include_significance?: boolean
      include_per_case?: boolean
      max_case_diffs?: number
    },
  ): Promise<RagasRegressionRunDiffResponse> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}/diff`, { params })
    return data
  },

  async exportRegressionRunDiffHtml(runId: string, params: { base_run_id: string; redact?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}/diff/export-html`, {
      params,
      responseType: 'blob',
    })
    return data as Blob
  },

  async exportRegressionRunBundle(
    runId: string,
    params?: {
      include_text?: boolean
      include_contexts?: boolean
      redact_ids?: boolean
      max_items?: number
      max_citations?: number
      download?: boolean
    },
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}/export-bundle`, {
      params,
      responseType: 'blob',
    })
    return data as Blob
  },

  async purgeRegressionRuns(params?: {
    retention_days?: number
    max_delete?: number
    dry_run?: boolean
    dataset_id?: string
  }): Promise<unknown> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/runs/purge', null, { params })
    return data
  },

  async runKgSearchDiagnostics(payload: KGSearchDiagnosticsRequest): Promise<KGSearchDiagnosticsResponse> {
    const { data } = await apiClient.post('/evaluations/kg/search/diagnostics', payload)
    return data
  },

  async listKgSearchDiagnosticsRuns(params: KGSearchDiagnosticsRunListParams): Promise<KGSearchDiagnosticsRunList> {
    const { data } = await apiClient.get('/evaluations/kg/search/diagnostics/runs', { params })
    return data
  },

  async getKgSearchDiagnosticsRun(runId: string): Promise<KGSearchDiagnosticsRunDetail> {
    const { data } = await apiClient.get(`/evaluations/kg/search/diagnostics/runs/${runId}`)
    return data
  },

  async getKgQualityReport(params: {
    dataset_id: string
    document_limit?: number
    pipeline_hash?: string
  }): Promise<JsonObject> {
    const { data } = await apiClient.get('/evaluations/kg/quality/report', { params })
    return data
  },
}
