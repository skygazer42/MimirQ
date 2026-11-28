// @vitest-environment happy-dom

import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QuotaSummary } from './quota-summary'
import { buildQuotaReadings } from './usage-model'

vi.stubGlobal('React', React)
const viewport = vi.hoisted(() => ({ desktop: false }))
vi.mock('@/hooks/use-media-query', () => ({ useMediaQuery: () => viewport.desktop }))

describe('quota disclosure', () => {
  beforeEach(() => {
    viewport.desktop = false
  })
  it('collapses only five explicitly disabled quotas and retains each real status', () => {
    const quotas = buildQuotaReadings(undefined, undefined).map((quota) => ({ ...quota, enabled: false }))
    const output = renderToStaticMarkup(<QuotaSummary quotas={quotas} pending={{ chat: false, tenant: false }} />)
    expect(output).toContain('配额未启用（5 项）')
    expect(output).toContain('<details')
    expect(output).not.toContain(' open=')
    expect(output.match(/>未启用</g)).toHaveLength(5)
  })

  it.each([true, undefined])('keeps quotas expanded if one is enabled or unknown (%s)', (enabled) => {
    const quotas = buildQuotaReadings(undefined, undefined).map((quota, index) => ({
      ...quota,
      enabled: index === 0 ? enabled : false,
    }))
    const output = renderToStaticMarkup(<QuotaSummary quotas={quotas} pending={{ chat: false, tenant: false }} />)
    expect(output).not.toContain('<details')
    expect(output).not.toContain('配额未启用（5 项）')
  })

  it('shows all five disabled quotas in the desktop rail without a disclosure', () => {
    viewport.desktop = true
    const quotas = buildQuotaReadings(undefined, undefined).map((quota) => ({ ...quota, enabled: false }))
    const output = renderToStaticMarkup(<QuotaSummary quotas={quotas} pending={{ chat: false, tenant: false }} />)
    expect(output).not.toContain('<details')
    expect(output.match(/>未启用</g)).toHaveLength(5)
    expect(output).toContain('aria-label="配额概览"')
  })

  it('distinguishes missing readings from pending and disabled quotas', () => {
    const quotas = buildQuotaReadings(undefined, undefined)
    const output = renderToStaticMarkup(<QuotaSummary quotas={quotas} pending={{ chat: true, tenant: false }} />)
    expect(output).not.toContain('<details')
    expect(output.match(/>未取得</g)).toHaveLength(4)
    expect(output).toContain('aria-busy="true"')
    expect(output).not.toContain('>未启用<')
  })
})
