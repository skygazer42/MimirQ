import { toApiErrorInfo, withRequestId } from '@/lib/api-errors'

function createFetchResponseError(response: Response, data: unknown, fallbackMessage: string, cause?: unknown): Error {
  const metadata = { status: response.status, data, headers: response.headers }
  const info = toApiErrorInfo({ response: metadata }, fallbackMessage)
  const options = cause === undefined ? undefined : { cause }
  return Object.assign(new Error(withRequestId(info.message, info.requestId), options), {
    requestId: info.requestId,
    response: metadata,
  })
}

export async function buildFetchError(response: Response, fallbackMessage: string): Promise<Error> {
  const message = `${fallbackMessage} (HTTP ${response.status})`
  let data: string
  try {
    data = await response.text()
  } catch (cause) {
    if (cause instanceof Error && cause.name === 'AbortError') throw cause
    return createFetchResponseError(response, undefined, `${message}：读取错误详情失败`, cause)
  }
  return createFetchResponseError(response, data, message)
}
