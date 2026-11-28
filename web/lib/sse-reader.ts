import { extractHeaderRequestId, withRequestId } from '@/lib/api-errors'
import { reportClientWarning } from '@/lib/client-logging'
import { createSseDataParser } from '@/lib/sse'

function createSseResponseError(response: Response, message: string): Error {
  const requestId = extractHeaderRequestId(response.headers)
  return Object.assign(new Error(withRequestId(message, requestId)), {
    requestId,
    response: { status: response.status, headers: response.headers },
  })
}

export async function readSseDataStrings(
  response: Response,
  onData: (data: string) => void,
  onStart?: () => void,
): Promise<void> {
  if (response.body === null) {
    throw createSseResponseError(response, 'SSE response has no body')
  }

  const reader = response.body.getReader()
  try {
    const contentType = response.headers.get('Content-Type')
    if (contentType === null || contentType.split(';')[0].trim().toLowerCase() !== 'text/event-stream') {
      throw createSseResponseError(response, 'Expected a text/event-stream response')
    }
    onStart?.()

    const decoder = new TextDecoder()
    const parser = createSseDataParser()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      for (const data of parser.feed(decoder.decode(value, { stream: true }))) onData(data)
    }
    for (const data of parser.feed(decoder.decode())) onData(data)
  } catch (error) {
    try {
      await reader.cancel(error)
    } catch (cleanupError) {
      if (!Object.is(cleanupError, error)) reportClientWarning('Failed to cancel SSE response reader', cleanupError)
    }
    throw error
  } finally {
    reader.releaseLock()
  }
}
