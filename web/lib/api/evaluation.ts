import { matchesResourceId } from '@/lib/resource-id'

import type {
  KGSearchDiagnosticsRequest,
  KGSearchDiagnosticsResponse,
  KGSearchDiagnosticsRunDetail,
  KGSearchDiagnosticsRunList,
  KGSearchDiagnosticsRunListParams,
  KGQualityReport,
  SyntheticHardcaseGenerateRequest,
  SyntheticHardcaseGenerateResponse,
  RegressionRunPurgeRequest,
  RegressionRunPurgeResponse,
  RagasConversationReadinessRequest,
  RagasConversationReadinessResponse,
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
  RegressionCaseImportRequest,
  RegressionCaseList,
  RegressionCasePatch,
  RegressionRun,
  RegressionRunCreate,
  RegressionRunDetail,
  RegressionRunList,
  RegressionRunLeaderboard,
  TestGenFromConversationsRequest,
  TestGenFromDocsRequest,
  TestGenResponse,
} from '@/types/evaluation'

import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import { parseApiResponse } from '@/lib/openapi-request'
import {
  regressionRunSchema,
  regressionRunListSchema,
  regressionRunDetailSchema,
  regressionAblationBatchSchema,
  regressionRunLeaderboardSchema,
} from '@/lib/regression-run-schema'
import {
  regressionCaseSchema,
  regressionCaseListSchema,
  regressionCaseBundleSchema,
  regressionCaseImportRequestSchema,
  regressionCaseImportResponseSchema,
  type RegressionCaseWindow,
} from '@/lib/regression-case-schema'
import { regressionRunDiffSchema } from '@/lib/regression-diff-schema'
import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import {
  ragasConversationReadinessRequestSchema,
  ragasConversationReadinessSchema,
  ragasRunCreateSchema,
  ragasRunSchema,
  ragasRunListSchema,
  ragasRunDetailSchema,
} from '@/lib/ragas-conversation-schema'
import {
  syntheticHardcaseRequestSchema,
  syntheticHardcaseResponseSchema,
  regressionPurgeRequestSchema,
  regressionPurgeResponseSchema,
} from '@/lib/evaluation-ops-schema'
import {
  kgDiagnosticsRequestSchema,
  kgDiagnosticsResponseSchema,
  kgDiagnosticsRunListSchema,
  kgDiagnosticsRunListRequestSchema,
  kgDiagnosticsRunDetailSchema,
  kgQualityRequestSchema,
  kgQualityReportSchema,
} from '@/lib/kg-diagnostics-schema'
import {
  documentQuestionRequestSchema,
  conversationQuestionRequestSchema,
  questionGenerationResponseSchema,
} from '@/lib/question-generation-schema'

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

export const evaluationApi = {
  async getRagasConversationReadiness(
    params: RagasConversationReadinessRequest,
    options?: ApiRequestOptions,
  ): Promise<RagasConversationReadinessResponse> {
    const request = ragasConversationReadinessRequestSchema.parse(params)
    const response = await apiClient.post<unknown>('/evaluations/ragas/conversation-readiness', request, {
      signal: options?.signal,
    })
    const result = parseApiResponse(response, ragasConversationReadinessSchema, 'RagasConversationReadiness')
    const requestedIds = new Set(request.conversation_ids.map((id) => id.toLowerCase()))
    const returnedIds = result.items.map((item) => item.conversation_id.toLowerCase())
    if (new Set(returnedIds).size !== returnedIds.length || returnedIds.some((id) => !requestedIds.has(id))) {
      throw new Error('对话评测状态的身份不匹配，请重新读取')
    }
    return result
  },

  async createRagasRun(params: RagasRunCreateRequest): Promise<RagasRun> {
    const request = ragasRunCreateSchema.parse(params)
    const response = await apiClient.post<unknown>('/evaluations/ragas/runs', request)
    const run = parseApiResponse(response, ragasRunSchema, 'RagasRun')
    if (!matchesResourceId(run.conversation_id, request.conversation_id)) {
      throw new Error('创建回执的对话不匹配，请先读取运行记录确认')
    }
    return run
  },

  async listRagasRuns(
    params?: { skip?: number; limit?: number; conversation_id?: string },
    options?: ApiRequestOptions,
  ): Promise<RagasRunList> {
    const response = await apiClient.get<unknown>('/evaluations/ragas/runs', { params, signal: options?.signal })
    const page = parseApiResponse(response, ragasRunListSchema, 'RagasRunList')
    const conversationId = params?.conversation_id
    if (
      page.total < page.items.length ||
      new Set(page.items.map((run) => run.id.toLowerCase())).size !== page.items.length ||
      (conversationId !== undefined &&
        page.items.some((run) => !matchesResourceId(run.conversation_id, conversationId)))
    ) {
      throw new Error('运行记录的数量、身份或对话不匹配，请重新读取')
    }
    return page
  },

  async getRagasRun(
    runId: string,
    params?: { include_items?: boolean; include_contexts?: boolean },
    options?: ApiRequestOptions,
  ): Promise<RagasRunDetail> {
    const response = await apiClient.get<unknown>(`/evaluations/ragas/runs/${encodeURIComponent(runId)}`, {
      params,
      signal: options?.signal,
    })
    const detail = parseApiResponse(response, ragasRunDetailSchema, 'RagasRunDetail')
    if (
      !matchesResourceId(detail.run.id, runId) ||
      detail.items.some((item) => !matchesResourceId(item.run_id, runId)) ||
      new Set(detail.items.map((item) => item.id.toLowerCase())).size !== detail.items.length
    ) {
      throw new Error('评测详情的运行或样本身份不匹配，请重新读取')
    }
    return detail
  },

  async createRegressionCase(params: RegressionCaseCreate): Promise<RegressionCase> {
    const response = await apiClient.post<unknown>('/evaluations/ragas/regression/cases', params)
    const created = parseApiResponse(response, regressionCaseSchema, 'RegressionCase')
    if (!matchesResourceId(created.dataset_id, params.dataset_id))
      throw new Error('创建回执的数据集不匹配，请先刷新样本列表确认')
    return created
  },

  async listRegressionCases(
    params?: { skip?: number; limit?: number; dataset_id?: string },
    options?: ApiRequestOptions,
  ): Promise<RegressionCaseList> {
    const response = await apiClient.get<unknown>('/evaluations/ragas/regression/cases', {
      params,
      signal: options?.signal,
    })
    const page = parseApiResponse(response, regressionCaseListSchema, 'RegressionCaseList')
    const datasetId = params?.dataset_id
    if (datasetId !== undefined && page.items.some((item) => !matchesResourceId(item.dataset_id, datasetId))) {
      throw new Error('返回样本的数据集不匹配，请重新读取')
    }
    return page
  },

  async listRegressionCaseWindow(datasetId: string, options?: ApiRequestOptions): Promise<RegressionCaseWindow> {
    const firstPage = await evaluationApi.listRegressionCases({ dataset_id: datasetId, skip: 0, limit: 200 }, options)
    const targetCount = Math.min(firstPage.total, 1000)
    const items = [...firstPage.items]
    while (items.length < targetCount) {
      const page = await evaluationApi.listRegressionCases(
        { dataset_id: datasetId, skip: items.length, limit: Math.min(200, targetCount - items.length) },
        options,
      )
      if (page.total !== firstPage.total) throw new Error('评测样本在读取期间发生变化，请重新读取')
      if (page.items.length === 0) throw new Error('评测样本尚未完整返回，请重新读取')
      items.push(...page.items)
    }
    if (
      items.length !== targetCount ||
      new Set(items.map((item) => item.id)).size !== targetCount ||
      items.some((item) => !matchesResourceId(item.dataset_id, datasetId))
    ) {
      throw new Error('评测样本数量、身份或数据集不匹配，请重新读取')
    }
    return { total: firstPage.total, items, fullyLoaded: items.length === firstPage.total }
  },

  async exportRegressionCases(
    params: { dataset_id: string },
    options?: ApiRequestOptions,
  ): Promise<RegressionCaseBundleV1> {
    const response = await apiClient.get<unknown>('/evaluations/ragas/regression/cases/export', {
      params,
      signal: options?.signal,
    })
    const bundle = parseApiResponse(response, regressionCaseBundleSchema, 'RegressionCaseBundle')
    if (!matchesResourceId(bundle.dataset_id, params.dataset_id)) throw new Error('导出文件的数据集与当前选择不匹配')
    return bundle
  },

  async importRegressionCases(payload: RegressionCaseImportRequest): Promise<RegressionCaseImportResponse> {
    const request = regressionCaseImportRequestSchema.parse(payload)
    const response = await apiClient.post<unknown>('/evaluations/ragas/regression/cases/import', request)
    const receipt = parseApiResponse(response, regressionCaseImportResponseSchema, 'RegressionCaseImport')
    if (receipt.created + receipt.updated + receipt.skipped !== request.items.length) {
      throw new Error('导入回执数量与原请求不匹配，请先读取样本列表确认')
    }
    return receipt
  },

  async deleteRegressionCase(caseId: string): Promise<void> {
    await apiClient.delete(`/evaluations/ragas/regression/cases/${encodeURIComponent(caseId)}`)
  },

  async patchRegressionCase(caseId: string, payload: RegressionCasePatch): Promise<RegressionCase> {
    const response = await apiClient.patch<unknown>(
      `/evaluations/ragas/regression/cases/${encodeURIComponent(caseId)}`,
      payload,
    )
    const updated = parseApiResponse(response, regressionCaseSchema, 'RegressionCase')
    if (!matchesResourceId(updated.id, caseId)) throw new Error('更新回执的样本不匹配，请先刷新样本列表确认')
    return updated
  },

  async generateSyntheticHardcases(
    payload: SyntheticHardcaseGenerateRequest,
  ): Promise<SyntheticHardcaseGenerateResponse> {
    const request = syntheticHardcaseRequestSchema.parse(payload)
    const response = await apiClient.post<unknown>('/evaluations/ragas/regression/cases/synthetic-hardcases', request, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    const receipt = parseApiResponse(response, syntheticHardcaseResponseSchema, 'SyntheticHardcaseGeneration')
    if (
      !matchesResourceId(receipt.dataset_id, request.dataset_id) ||
      (request.dry_run === true && receipt.created !== 0) ||
      (request.max_created !== undefined && request.max_created > 0 && receipt.created > request.max_created)
    ) {
      throw new Error('困难样例回执与原请求范围不一致，请先读取用例列表确认')
    }
    return receipt
  },

  async generateFromDocuments(params: TestGenFromDocsRequest): Promise<TestGenResponse> {
    const request = documentQuestionRequestSchema.parse(params)
    const response = await apiClient.post<unknown>('/evaluations/ragas/test-gen/from-documents', request, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    const result = parseApiResponse(response, questionGenerationResponseSchema, 'DocumentQuestionGeneration')
    if (result.status === 'failed') return result
    if (
      result.generated_questions.some(
        ({ source_type, source_id }) =>
          source_type !== 'document' ||
          source_id === null ||
          (request.document_ids !== undefined &&
            request.document_ids.length > 0 &&
            !request.document_ids.some((id) => matchesResourceId(source_id, id))),
      )
    ) {
      throw new Error('生成结果的文档来源与原请求不匹配，请先读取用例列表确认')
    }
    if (request.auto_save_as_cases === false) {
      if (result.saved_case_ids.length > 0) throw new Error('仅预览请求返回了已保存身份，请先读取用例列表确认')
      return result
    }
    const savedIds: string[] = []
    for (const question of result.generated_questions) {
      const save = question.metadata.auto_save
      if (save === undefined) throw new Error('生成结果没有提供保存状态，请先读取用例列表确认')
      if (save.saved) savedIds.push(save.case_id)
    }
    if (
      savedIds.length !== result.saved_case_ids.length ||
      savedIds.some((id, index) => id !== result.saved_case_ids[index])
    ) {
      throw new Error('逐题保存结果与批次回执不一致，请先读取用例列表确认')
    }
    return result
  },

  async generateFromConversations(params: TestGenFromConversationsRequest): Promise<TestGenResponse> {
    const request = conversationQuestionRequestSchema.parse(params)
    const response = await apiClient.post<unknown>('/evaluations/ragas/test-gen/from-conversations', request, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    const result = parseApiResponse(response, questionGenerationResponseSchema, 'ConversationQuestionGeneration')
    if (result.status === 'failed') return result
    if (result.generated_questions.some((question) => question.source_type !== 'conversation')) {
      throw new Error('生成结果的来源类型与原请求不匹配，请先读取用例列表确认')
    }
    const expectedSaved = request.auto_save_as_cases === false ? 0 : result.generated_questions.length
    if (result.saved_case_ids.length !== expectedSaved) {
      throw new Error('对话用例保存回执数量不匹配，请先读取用例列表确认')
    }
    return result
  },

  async createRegressionRun(params: RegressionRunCreate): Promise<RegressionRun> {
    const response = await apiClient.post<unknown>('/evaluations/ragas/regression/runs', params)
    const created = parseApiResponse(response, regressionRunSchema, 'RegressionRunCreated')
    if (!matchesResourceId(created.dataset_id, params.dataset_id))
      throw new Error('运行回执的数据集不匹配，请先读取运行记录确认')
    return created
  },

  async createRegressionAblationBatch(
    params: RegressionAblationBatchRequest,
  ): Promise<RegressionAblationBatchResponse> {
    const response = await apiClient.post<unknown>('/evaluations/ragas/regression/ablation/batch', params)
    const batch = parseApiResponse(response, regressionAblationBatchSchema, 'RegressionAblationBatch')
    const expected = Object.values(params.grid).reduce((total, values) => total * values.length, 1)
    if (batch.total !== expected) throw new Error('回执与提交的组合数不一致，请先读取运行记录确认')
    return batch
  },

  async listRegressionRuns(
    params?: { skip?: number; limit?: number; dataset_id?: string },
    options: ApiRequestOptions = {},
  ): Promise<RegressionRunList> {
    const response = await apiClient.get<unknown>('/evaluations/ragas/regression/runs', {
      params,
      signal: options.signal,
    })
    return parseApiResponse(response, regressionRunListSchema, 'RegressionRunList')
  },

  async getRegressionRunLeaderboard(
    params: {
      dataset_id: string
      metric_key?: string
      limit?: number
      include_incomplete?: boolean
      max_candidates?: number
    },
    options?: ApiRequestOptions,
  ): Promise<RegressionRunLeaderboard> {
    const response = await apiClient.get<unknown>('/evaluations/ragas/regression/runs/leaderboard', {
      params,
      signal: options?.signal,
    })
    const board = parseApiResponse(response, regressionRunLeaderboardSchema, 'RegressionRunLeaderboard')
    if (params.metric_key !== undefined && board.metric_key !== params.metric_key) {
      throw new Error('返回排行的指标与所选指标不匹配，请重新读取')
    }
    return board
  },

  async getRegressionRun(
    runId: string,
    params?: { include_items?: boolean; include_contexts?: boolean },
    options: ApiRequestOptions = {},
  ): Promise<RegressionRunDetail> {
    const response = await apiClient.get<unknown>(`/evaluations/ragas/regression/runs/${encodeURIComponent(runId)}`, {
      params,
      signal: options.signal,
    })
    const detail = parseApiResponse(response, regressionRunDetailSchema, 'RegressionRunDetail')
    if (
      !matchesResourceId(detail.run.id, runId) ||
      detail.items.some((item) => !matchesResourceId(item.run_id, runId))
    ) {
      throw new Error('返回运行明细的身份不匹配，请重新读取')
    }
    return detail
  },

  async diffRegressionRuns(
    runId: string,
    params: {
      base_run_id: string
      include_significance?: boolean
      include_per_case?: boolean
      max_case_diffs?: number
    },
    options?: ApiRequestOptions,
  ): Promise<RagasRegressionRunDiffResponse> {
    const response = await apiClient.get<unknown>(
      `/evaluations/ragas/regression/runs/${encodeURIComponent(runId)}/diff`,
      { params, signal: options?.signal },
    )
    const diff = parseApiResponse(response, regressionRunDiffSchema, 'RegressionRunDiff')
    if (!matchesResourceId(diff.base_run_id, params.base_run_id) || !matchesResourceId(diff.target_run_id, runId)) {
      throw new Error('返回对比的基线或候选身份不匹配，请重新读取')
    }
    return diff
  },

  async exportRegressionRunDiffHtml(
    runId: string,
    params: { base_run_id: string; redact?: boolean },
    options?: ApiRequestOptions,
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(
      `/evaluations/ragas/regression/runs/${encodeURIComponent(runId)}/diff/export-html`,
      {
        params,
        responseType: 'blob',
        signal: options?.signal,
      },
    )
    return data
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
    options?: ApiRequestOptions,
  ): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(
      `/evaluations/ragas/regression/runs/${encodeURIComponent(runId)}/export-bundle`,
      {
        params,
        responseType: 'blob',
        signal: options?.signal,
      },
    )
    return data
  },

  async purgeRegressionRuns(params?: RegressionRunPurgeRequest): Promise<RegressionRunPurgeResponse> {
    const request = regressionPurgeRequestSchema.parse(params)
    const response = await apiClient.post<unknown>('/evaluations/ragas/regression/runs/purge', null, {
      params: request,
    })
    const receipt = parseApiResponse(response, regressionPurgeResponseSchema, 'RegressionRunPurge')
    if (
      (request?.dataset_id !== undefined && !matchesResourceId(receipt.dataset_id, request.dataset_id)) ||
      (request?.dry_run !== undefined && receipt.dry_run !== request.dry_run) ||
      (request?.max_delete !== undefined && receipt.max_delete !== request.max_delete) ||
      (request?.retention_days !== undefined && receipt.retention_days !== request.retention_days)
    ) {
      throw new Error('清理回执与原请求不一致，请先读取运行记录确认')
    }
    return receipt
  },

  async runKgSearchDiagnostics(payload: KGSearchDiagnosticsRequest): Promise<KGSearchDiagnosticsResponse> {
    const request = kgDiagnosticsRequestSchema.parse(payload)
    const response = await apiClient.post<unknown>('/evaluations/kg/search/diagnostics', request, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    const report = parseApiResponse(response, kgDiagnosticsResponseSchema, 'KGDiagnostics')
    const requestedCaseIds = request.case_ids
    if (
      !matchesResourceId(report.summary.dataset_id, request.dataset_id) ||
      (requestedCaseIds !== undefined &&
        requestedCaseIds.length > 0 &&
        report.items.some((item) => !requestedCaseIds.some((id) => matchesResourceId(item.case_id, id))))
    ) {
      throw new Error('诊断报告的数据集或样本范围不匹配，请先读取运行记录确认')
    }
    return report
  },

  async listKgSearchDiagnosticsRuns(
    params: KGSearchDiagnosticsRunListParams,
    options?: ApiRequestOptions,
  ): Promise<KGSearchDiagnosticsRunList> {
    const request = kgDiagnosticsRunListRequestSchema.parse(params)
    const response = await apiClient.get<unknown>('/evaluations/kg/search/diagnostics/runs', {
      params: request,
      signal: options?.signal,
    })
    const page = parseApiResponse(response, kgDiagnosticsRunListSchema, 'KGDiagnosticsRunList')
    if (page.items.some((item) => !matchesResourceId(item.dataset_id, request.dataset_id)))
      throw new Error('运行列表的数据集不匹配')
    return page
  },

  async getKgSearchDiagnosticsRun(runId: string, options?: ApiRequestOptions): Promise<KGSearchDiagnosticsRunDetail> {
    const response = await apiClient.get<unknown>(
      `/evaluations/kg/search/diagnostics/runs/${encodeURIComponent(runId)}`,
      {
        signal: options?.signal,
      },
    )
    const detail = parseApiResponse(response, kgDiagnosticsRunDetailSchema, 'KGDiagnosticsRunDetail')
    if (!matchesResourceId(detail.run.id, runId)) throw new Error('运行明细的身份与原请求不匹配')
    return detail
  },

  async getKgQualityReport(
    params: {
      dataset_id: string
      document_limit?: number
      pipeline_hash?: string
    },
    options?: ApiRequestOptions,
  ): Promise<KGQualityReport> {
    const request = kgQualityRequestSchema.parse(params)
    const response = await apiClient.get<unknown>('/evaluations/kg/quality/report', {
      params: request,
      signal: options?.signal,
    })
    const report = parseApiResponse(response, kgQualityReportSchema, 'KGQualityReport')
    if (!matchesResourceId(report.scope.dataset_id, request.dataset_id))
      throw new Error('质量报告的数据集与原请求不匹配')
    return report
  },
}
