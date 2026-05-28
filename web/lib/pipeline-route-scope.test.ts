import { describe, expect, it } from 'vitest'

import {
  needsPipelineProvidersForPathname,
  normalizePipelinePathname,
} from './pipeline-route-scope'

describe('pipeline route scope', () => {
  it('recognizes locale-prefixed pipeline routes used by compatibility links', () => {
    expect(normalizePipelinePathname('/zh-CN/settings')).toBe('/settings')
    expect(normalizePipelinePathname('/zh-CN/knowledge/quarantine')).toBe('/knowledge/quarantine')
    expect(needsPipelineProvidersForPathname('/zh-CN/settings')).toBe(true)
    expect(needsPipelineProvidersForPathname('/zh-CN/chunk-preview')).toBe(true)
  })

  it('does not treat arbitrary non-pipeline locale routes as pipeline routes', () => {
    expect(normalizePipelinePathname('/zh-CN/history')).toBe('/zh-CN/history')
    expect(needsPipelineProvidersForPathname('/zh-CN/history')).toBe(false)
    expect(needsPipelineProvidersForPathname('/usage')).toBe(false)
  })
})
