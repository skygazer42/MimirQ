import { z } from 'zod'

import type { DatasetPrecheckScanRunOut } from '@/types/datasets'
import { getAuthHeaders } from '@/lib/auth-headers'
import { authenticatedFetch } from '@/lib/authenticated-fetch'
import { extractHeaderRequestId, withRequestId } from '@/lib/api-errors'
import { buildFetchError } from '@/lib/fetch-errors'
import { API_V1_BASE_URL } from '@/lib/env'
import { withPreferredLanguageHeader } from '@/lib/preferred-language'
import { generateRequestId } from '@/lib/request-id'
import { readSseDataStrings } from '@/lib/sse-reader'
import { recordSchema } from '@/lib/response-schema'

const scanRunSchema: z.ZodType<DatasetPrecheckScanRunOut> = z.object({
  id: z.string(),
  tenant_id: z.string(),
  dataset_id: z.string(),
  requested_by: z.string().nullable().optional(),
  kind: z.string(),
  status: z
    .string()
    .toLowerCase()
    .pipe(z.enum(['pending', 'running', 'completed', 'failed', 'cancelled'])),
  progress: z.number().int(),
  config: recordSchema,
  summary: recordSchema,
  artifacts: recordSchema,
  error_message: z.string().nullable().optional(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  created_at: z.string().nullable().optional(),
  updated_at: z.string().nullable().optional(),
})

export const sseApi = {
  async streamPrecheckScanEvents(
    datasetId: string,
    scanRunId: string,
    onRun: (run: DatasetPrecheckScanRunOut) => void,
    options: { signal?: AbortSignal } = {},
  ): Promise<{ requestId: string }> {
    const requestId = generateRequestId()
    const response = await authenticatedFetch(
      `${API_V1_BASE_URL}/datasets/${encodeURIComponent(datasetId)}/precheck/scan-runs/${encodeURIComponent(scanRunId)}/events`,
      {
        method: 'GET',
        headers: withPreferredLanguageHeader({
          Accept: 'text/event-stream',
          ...getAuthHeaders(),
          'X-Request-ID': requestId,
        }),
        signal: options.signal,
      },
    )
    if (!response.ok) throw await buildFetchError(response, 'Precheck SSE failed')

    const backendRequestId = extractHeaderRequestId(response.headers)
    const metadata = { requestId: backendRequestId === undefined ? requestId : backendRequestId }
    let sawTerminalRun = false
    await readSseDataStrings(response, (data) => {
      if (options.signal?.aborted) return
      const payload: unknown = JSON.parse(data)
      const run = scanRunSchema.parse(payload)
      if (
        run.id.toLowerCase() !== scanRunId.toLowerCase() ||
        run.dataset_id.toLowerCase() !== datasetId.toLowerCase()
      ) {
        throw new Error(withRequestId('Precheck SSE returned a different scan run', metadata.requestId))
      }
      sawTerminalRun = run.status !== 'pending' && run.status !== 'running'
      onRun(run)
    })
    options.signal?.throwIfAborted()
    if (!sawTerminalRun) {
      throw new Error(withRequestId('Precheck SSE ended before scan completion', metadata.requestId))
    }
    return metadata
  },
}
