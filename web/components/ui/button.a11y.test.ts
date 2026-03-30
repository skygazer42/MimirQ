import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Button } from './button'

describe('Button accessibility', () => {
  it('mirrors the title into aria-label for icon buttons', () => {
    const html = renderToStaticMarkup(
      React.createElement(
        Button,
        {
          type: 'button',
          size: 'icon',
          variant: 'ghost',
          title: '刷新图谱',
        },
        React.createElement('span', { 'aria-hidden': 'true' }, 'R')
      )
    )

    expect(html).toContain('title="刷新图谱"')
    expect(html).toContain('aria-label="刷新图谱"')
  })

  it('mirrors the aria-label into title for icon buttons', () => {
    const html = renderToStaticMarkup(
      React.createElement(
        Button,
        {
          type: 'button',
          size: 'icon',
          variant: 'ghost',
          'aria-label': '关闭面板',
        },
        React.createElement('span', { 'aria-hidden': 'true' }, 'X')
      )
    )

    expect(html).toContain('aria-label="关闭面板"')
    expect(html).toContain('title="关闭面板"')
  })
})
