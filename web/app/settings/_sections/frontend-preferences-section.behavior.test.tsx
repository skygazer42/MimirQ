// @vitest-environment happy-dom

import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PARSER_BACKEND_OPTIONS } from '@/lib/parser-options'

const availability = vi.hoisted(() => new Map<string, boolean>())
vi.mock('@/contexts/pipeline-capabilities-context', () => ({
  usePipelineCapabilities: () => ({
    capabilities: { pdf_backends: [{ name: 'docling', available: false, notes: '尚未启用 Docling 服务' }] },
    loading: false,
    error: null,
    refresh: vi.fn(),
    parserBackendAvailable: (name: string) => availability.get(name),
  }),
}))
vi.mock('@/components/pipeline-options-panel', () => ({ PipelineOptionsPanel: () => null }))

import { FrontendPreferencesSection } from './frontend-preferences-section'

function choices(parserBackend = 'auto') {
  const onChange = vi.fn()
  const container = document.createElement('div')
  container.innerHTML = renderToStaticMarkup(
    <FrontendPreferencesSection
      parserBackend={parserBackend}
      setParserBackend={onChange}
      chunkStrategy="langchain_recursive"
      setChunkStrategy={vi.fn()}
    />,
  )
  return { group: container.querySelector('[role="radiogroup"]')!, onChange }
}

beforeEach(() => availability.clear())

describe('pipeline choice disclosure', () => {
  it('shows available parsers first and folds unavailable or unknown options with their reasons', () => {
    availability.set('markitdown', true)
    availability.set('docling', false)
    const { group } = choices()
    expect([...group.querySelectorAll(':scope > label input')].map((input) => input.getAttribute('value'))).toEqual([
      'auto',
      'basic',
      'markitdown',
    ])
    const details = group.querySelector('details')!
    expect(details.open).toBe(false)
    const docling = details.querySelector<HTMLInputElement>('input[value="docling"]')!
    expect(docling.disabled).toBe(true)
    expect(docling.closest('label')?.textContent).toContain('尚未启用 Docling 服务')
    expect(details.textContent).toContain('尚未读取到该解析器的可用状态')
    expect(details.textContent).toContain('可在「解析服务」中启用')
  })

  it('opens the disclosure for a selected unavailable parser without changing the saved value', () => {
    availability.set('docling', false)
    const { group, onChange } = choices('docling')
    expect(group.querySelector('details')!.open).toBe(true)
    expect(group.querySelector<HTMLInputElement>('input[value="docling"]')!.checked).toBe(true)
    expect(onChange).not.toHaveBeenCalled()
  })

  it('keeps the first six available choices visible and opens overflow for the current selection', () => {
    for (const option of PARSER_BACKEND_OPTIONS) availability.set(option.value, true)
    const { group } = choices('markitdown')
    expect(group.querySelectorAll(':scope > label')).toHaveLength(6)
    expect(group.querySelectorAll('[data-disabled="true"]')).toHaveLength(0)
    const details = group.querySelector('details')!
    expect(details.open).toBe(true)
    expect(details.querySelector<HTMLInputElement>('input[value="markitdown"]')!.checked).toBe(true)
  })
})
