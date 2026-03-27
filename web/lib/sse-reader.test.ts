import { describe, expect, it, vi } from 'vitest'

import { readSseDataStrings } from './sse-reader'

describe('readSseDataStrings', () => {
  it('reads SSE frames across chunks', async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"a":'))
        controller.enqueue(encoder.encode('1}\n\n'))
        controller.enqueue(encoder.encode('data: ok\n\n'))
        controller.close()
      },
    })

    const out: string[] = []
    await readSseDataStrings(stream.getReader(), (data) => out.push(data))
    expect(out).toEqual(['{"a":1}', 'ok'])
  })

  it('calls onError when onData throws', async () => {
    const encoder = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: 1\n\n'))
        controller.enqueue(encoder.encode('data: 2\n\n'))
        controller.close()
      },
    })

    const onError = vi.fn()
    const out: string[] = []
    await readSseDataStrings(
      stream.getReader(),
      (data) => {
        if (data === '1') throw new Error('boom')
        out.push(data)
      },
      onError
    )

    expect(out).toEqual(['2'])
    expect(onError).toHaveBeenCalled()
  })

  it('preserves multibyte unicode when UTF-8 code points split across chunks', async () => {
    const chunks = [
      Uint8Array.from([100, 97, 116, 97, 58, 32, 34, 229]),
      Uint8Array.from([174, 140, 230, 149, 180, 34, 10, 10]),
    ]

    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(chunk)
        }
        controller.close()
      },
    })

    const out: string[] = []
    await readSseDataStrings(stream.getReader(), (data) => out.push(data))

    expect(out).toEqual(['"完整"'])
  })
})
