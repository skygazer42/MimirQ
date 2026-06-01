import { createSseDataParser } from '@/lib/sse'

export async function readSseDataStrings(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onData: (data: string) => void,
  onError?: (error: unknown) => void
): Promise<void> {
  const decoder = new TextDecoder()
  const sse = createSseDataParser()

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    const chunkText = decoder.decode(value, { stream: true })
    for (const data of sse.feed(chunkText)) {
      try {
        onData(data)
      } catch (e) {
        onError?.(e)
      }
    }
  }

  // Flush remaining decoder output (best-effort).
  for (const data of sse.feed(decoder.decode())) {
    try {
      onData(data)
    } catch (e) {
      onError?.(e)
    }
  }
}
