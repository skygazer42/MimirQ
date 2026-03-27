import { getAuthHeaders } from '@/lib/auth-headers'
import { API_V1_BASE_URL } from '@/lib/env'
import { withPreferredLanguageHeader } from '@/lib/preferred-language'
import { generateRequestId } from '@/lib/request-id'

export type FrontendTracePayload = Readonly<{
  event: string
  duration_ms: number
  component?: string
  page?: string
  input_node_count?: number
  input_link_count?: number
  output_node_count?: number
  output_link_count?: number
  active_filter_count?: number
}>

export type FrontendTraceReportOptions = Readonly<{
  keepalive?: boolean
  signal?: AbortSignal
}>

export async function reportFrontendTrace(
  payload: FrontendTracePayload,
  options: FrontendTraceReportOptions = {}
): Promise<void> {
  const authHeaders = getAuthHeaders()
  if (!authHeaders.Authorization && !authHeaders['X-User-ID']) return

  const response = await fetch(`${API_V1_BASE_URL}/observability/frontend-traces`, {
    method: 'POST',
    headers: withPreferredLanguageHeader({
      'Content-Type': 'application/json',
      ...authHeaders,
      'X-Request-ID': generateRequestId(),
    }),
    body: JSON.stringify(payload),
    keepalive: options.keepalive === true,
    signal: options.signal,
  })

  if (!response.ok) {
    const requestId = response.headers.get('X-Request-ID')
    throw new Error(
      requestId
        ? `Frontend trace report failed (status=${response.status}, request_id=${requestId})`
        : `Frontend trace report failed (status=${response.status})`
    )
  }
}
