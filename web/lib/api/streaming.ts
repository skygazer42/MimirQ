import { getAuthHeaders } from '@/lib/auth-headers'
import { buildFetchError } from '@/lib/fetch-errors'
import { API_V1_BASE_URL } from '@/lib/env'
import { withPreferredLanguageHeader } from '@/lib/preferred-language'
import { generateRequestId } from '@/lib/request-id'
import { readSseDataStrings } from '@/lib/sse-reader'

export const sseApi = {
  async streamPrecheckScanEvents(
    datasetId: string,
    scanRunId: string,
    onJson: (jsonStr: string) => void,
    options: { onError?: (error: unknown) => void; signal?: AbortSignal } = {}
  ): Promise<{ requestId: string }> {
    const requestId = generateRequestId()

    const response = await fetch(`${API_V1_BASE_URL}/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/events`, {
      method: 'GET',
      headers: withPreferredLanguageHeader({
        Accept: 'text/event-stream',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      }),
      signal: options.signal,
    })

    if (!response.ok) {
      throw await buildFetchError(response, 'Precheck SSE failed')
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const backendRequestId = response.headers.get('X-Request-ID') || requestId
    await readSseDataStrings(reader, onJson, options.onError)
    return { requestId: backendRequestId }
  },
}
