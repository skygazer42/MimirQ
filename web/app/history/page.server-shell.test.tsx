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
  it('leaves authenticated data and URL selection to the client', () => {
    const element = HistoryPage()
    expect(element.props).toEqual({})
  })
})
