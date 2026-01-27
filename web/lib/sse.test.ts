import { describe, expect, it } from 'vitest'

import { createSseDataParser } from './sse'

describe('createSseDataParser', () => {
  it('parses single data frame', () => {
    const sse = createSseDataParser()
    expect(sse.feed('data: {"ok":true}\n\n')).toEqual(['{"ok":true}'])
  })

  it('ignores comment frames', () => {
    const sse = createSseDataParser()
    expect(sse.feed(': keepalive\n\n')).toEqual([])
  })

  it('handles CRLF', () => {
    const sse = createSseDataParser()
    expect(sse.feed('data: hi\r\n\r\n')).toEqual(['hi'])
  })

  it('joins multiple data lines', () => {
    const sse = createSseDataParser()
    expect(sse.feed('data: line1\ndata: line2\n\n')).toEqual(['line1\nline2'])
  })

  it('handles chunked frames', () => {
    const sse = createSseDataParser()
    expect(sse.feed('data: {"a":')).toEqual([])
    expect(sse.feed('1}\n\n')).toEqual(['{"a":1}'])
  })
})

