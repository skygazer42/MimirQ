import type {
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
} from '@/types'

import { apiClient } from '@/lib/api/core'

export interface RagasRun {
  id: string
  conversation_id?: string
  status: string
  metrics: string[]
  params: Record<string, any>
  summary: Record<string, any>
  error_message?: string
  created_at: string
  started_at?: string
  finished_at?: string
}

export interface RagasItem {
  id: string
  run_id: string
  turn_index: number
  user_message_id?: string
  assistant_message_id?: string
  user_input: string
  response: string
  retrieved_contexts?: string[] | null
  citations: any[]
  scores: Record<string, any>
  created_at: string
}

export interface RagasRunDetail {
  run: RagasRun
  items: RagasItem[]
}

export type KGHardcaseMode = 'off' | 'deterministic' | 'llm'

export interface KGSearchDiagnosticsRequest {
  dataset_id: string
  case_ids?: string[]
  max_cases?: number
  k?: number
  auto_extract_kg?: boolean
  extract_skills?: boolean | null
  extract_relations?: boolean | null
  hardcase_mode?: KGHardcaseMode
  hardcases_per_failed_case?: number
  max_failed_cases_for_hardcase?: number
  llm_temperature?: number
  persist_run?: boolean
}

export interface KGSearchDiagnosticsResponse {
  run_id?: string | null
  summary: Record<string, any>
  items: any[]
}

export interface KGSearchDiagnosticsRunOut {
  id: string
  tenant_id: string
  account_id?: string | null
  dataset_id: string
  status: string
  params: Record<string, any>
  summary: Record<string, any>
  created_at: string
}

export interface KGSearchDiagnosticsRunList {
  total: number
  items: KGSearchDiagnosticsRunOut[]
}

export interface KGSearchDiagnosticsRunDetail {
  run: KGSearchDiagnosticsRunOut
  items: any[]
}

export const evaluationApi = {
  async createRagasRun(params: {
    conversation_id: string
    metrics?: string[]
    max_turns?: number
    skip_empty_contexts?: boolean
    include_contexts_in_response?: boolean
  }): Promise<RagasRun> {
    const { data } = await apiClient.post('/evaluations/ragas/runs', params)
    return data
  },

  async listRagasRuns(params?: {
    skip?: number
    limit?: number
    conversation_id?: string
  }): Promise<{ total: number; items: RagasRun[] }> {
    const { data } = await apiClient.get('/evaluations/ragas/runs', { params })
    return data
  },

  async getRagasRun(
    runId: string,
    params?: { include_items?: boolean; include_contexts?: boolean }
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
    items: any[]
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
  }): Promise<any> {
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

  async createRegressionAblationBatch(params: RegressionAblationBatchRequest): Promise<RegressionAblationBatchResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/ablation/batch', params)
    return data
  },

  async listRegressionRuns(params?: {
    skip?: number
    limit?: number
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
  }): Promise<any> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/runs/leaderboard', { params })
    return data
  },

  async getRegressionRun(
    runId: string,
    params?: { include_items?: boolean; include_contexts?: boolean }
  ): Promise<RegressionRunDetail> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}`, { params })
    return data
  },

  async diffRegressionRuns(
    runId: string,
    params: { base_run_id: string; include_significance?: boolean; include_per_case?: boolean; max_case_diffs?: number }
  ): Promise<RagasRegressionRunDiffResponse> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}/diff`, { params })
    return data
  },

  async exportRegressionRunDiffHtml(
    runId: string,
    params: { base_run_id: string; redact?: boolean }
  ): Promise<Blob> {
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
    }
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
  }): Promise<any> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/runs/purge', null, { params })
    return data
  },

  async runKgSearchDiagnostics(payload: KGSearchDiagnosticsRequest): Promise<KGSearchDiagnosticsResponse> {
    const { data } = await apiClient.post('/evaluations/kg/search/diagnostics', payload)
    return data
  },

  async listKgSearchDiagnosticsRuns(params: { dataset_id: string; limit?: number }): Promise<KGSearchDiagnosticsRunList> {
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
  }): Promise<any> {
    const { data } = await apiClient.get('/evaluations/kg/quality/report', { params })
    return data
  },
}
