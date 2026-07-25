import React from 'react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('./page-client', () => ({
  default: (props: Record<string, unknown>) =>
    React.createElement('pre', {
      'data-props': JSON.stringify(props),
    }),
}))

import HistoryPage from './page'

describe('history page server shell', () => {
  it('passes only the requested conversation id and lets the client fetch authenticated data', async () => {
    const element = await HistoryPage({
      searchParams: Promise.resolve({ id: 'conv-42' }),
    })

    expect(element.props).toEqual({
      initialConversationId: 'conv-42',
    })
  })
})
