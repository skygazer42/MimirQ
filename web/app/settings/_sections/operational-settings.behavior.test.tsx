// @vitest-environment happy-dom

import React, { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  CacheConfig,
  ChatConfig,
  LangGraphConfig,
  NavigationConfig,
  ObservabilityConfig,
  SafetyConfig,
} from '@/types/settings'

import { NavigationVisibilitySection } from './navigation-visibility-section'
import { ObservabilitySection } from './observability-section'
import { RuntimeControlsSection } from './runtime-controls-section'

type Values = {
  navigation: NavigationConfig
  observability: ObservabilityConfig
  cache: CacheConfig
  chat: ChatConfig
  safety: SafetyConfig
  langgraph: LangGraphConfig
}

const cleanup: Array<() => void> = []

function initialValues(): Values {
  return {
    navigation: { user_visible_modules: [] },
    observability: {
      tool_call_log_enabled: true,
      tool_call_log_include_preview: false,
      tool_call_log_max_preview_chars: 500,
      agent_log_enabled: true,
      agent_log_include_execution_path: false,
      agent_log_max_preview_chars: 500,
      metrics_log_enabled: true,
      metrics_log_include_text: false,
    },
    cache: {
      upload_dedup_enabled: false,
      chat_response_cache_enabled: true,
      chat_response_cache_ttl_sec: 300,
      chat_response_cache_max_value_bytes: 200000,
      chat_response_cache_require_empty_history: false,
    },
    chat: { stream_heartbeat_sec: 0, stream_cancel_on_disconnect: false },
    safety: { pii_redaction_enabled: true, pii_redaction_mask: '', pii_stream_holdback_chars: 128 },
    langgraph: { use_subgraphs: false },
  }
}

function mount(extra: Partial<Values> = {}) {
  const onPatch = vi.fn<(scope: keyof Values, patch: object) => void>()
  function Harness() {
    const [values, setValues] = useState<Values>(() => ({ ...initialValues(), ...extra }))
    function update<K extends keyof Values>(scope: K, patch: Partial<Values[K]>) {
      onPatch(scope, patch)
      setValues((previous) => ({ ...previous, [scope]: { ...previous[scope], ...patch } }))
    }
    return (
      <>
        <NavigationVisibilitySection
          navigation={values.navigation}
          updateNavigation={(patch) => update('navigation', patch)}
        />
        <ObservabilitySection
          observability={values.observability}
          updateObservability={(patch) => update('observability', patch)}
        />
        <RuntimeControlsSection
          chat={values.chat}
          cache={values.cache}
          safety={values.safety}
          langgraph={values.langgraph}
          updateChat={(patch) => update('chat', patch)}
          updateCache={(patch) => update('cache', patch)}
          updateSafety={(patch) => update('safety', patch)}
          updateLangGraph={(patch) => update('langgraph', patch)}
        />
      </>
    )
  }
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  act(() => root.render(<Harness />))
  cleanup.push(() => {
    act(() => root.unmount())
    container.remove()
  })
  return { container, onPatch }
}

function input(scope: ParentNode, label: string) {
  const field = [...scope.querySelectorAll('div,span,label')].find(
    (node) => node.textContent?.trim() === label && node.parentElement?.querySelector('input'),
  )
  const target = field?.querySelector('input') ?? field?.parentElement?.querySelector('input')
  expect(target, `input ${label}`).toBeDefined()
  return target!
}

function toggle(scope: ParentNode, label: string) {
  const target = [...scope.querySelectorAll<HTMLButtonElement>('button[role="switch"]')].find(
    (node) => node.getAttribute('aria-label') === label,
  )
  expect(target, `switch ${label}`).toBeDefined()
  return target!
}

function click(scope: ParentNode, label: string) {
  act(() => toggle(scope, label).click())
}

function fill(target: HTMLInputElement, value: string, numericValue?: number) {
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(target, value)
    if (numericValue !== undefined) expect(target.valueAsNumber).toBe(numericValue)
    target.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})

afterEach(() => {
  cleanup
    .splice(0)
    .reverse()
    .forEach((dispose) => dispose())
  document.body.replaceChildren()
})

const integerFields = [
  ['结果摘要最大字符数', 'observability', 'tool_call_log_max_preview_chars'],
  ['错误摘要最大字符数', 'observability', 'agent_log_max_preview_chars'],
  ['缓存时长（秒）', 'cache', 'chat_response_cache_ttl_sec'],
  ['最大字节', 'cache', 'chat_response_cache_max_value_bytes'],
  ['流式缓冲字符', 'safety', 'pii_stream_holdback_chars'],
] as const

describe.each(integerFields)('%s numeric patch contract', (label, scope, key) => {
  it('emits the complete native exponent value', () => {
    const view = mount()
    fill(input(view.container, label), '1e3', 1000)
    expect(view.onPatch).toHaveBeenLastCalledWith(scope, { [key]: 1000 })
  })

  it('retains a fraction for the existing integer API validation', () => {
    const view = mount()
    fill(input(view.container, label), '1.5', 1.5)
    expect(view.onPatch).toHaveBeenLastCalledWith(scope, { [key]: 1.5 })
    expect(input(view.container, label).validity.stepMismatch).toBe(true)
  })

  it('keeps blank and explicit zero as zero without restoring display defaults', () => {
    const view = mount()
    fill(input(view.container, label), '')
    expect(view.onPatch).toHaveBeenLastCalledWith(scope, { [key]: 0 })
    expect(input(view.container, label).value).toBe('0')
    fill(input(view.container, label), '0', 0)
    expect(input(view.container, label).value).toBe('0')
  })
})

const navigationModules = [
  ['治理配置', 'governanceProfiles'],
  ['重复内容治理', 'commonLines'],
  ['知识图谱', 'knowledgeGraph'],
  ['图谱快照', 'graphSnapshots'],
  ['图谱检索评测', 'graphDiagnostics'],
  ['RAGAS 评测', 'ragas'],
  ['检索消融', 'ablations'],
  ['数据报告导出', 'reports'],
  ['提示词', 'prompts'],
] as const

describe('navigation selection and normalization', () => {
  it.each(navigationModules)('emits the existing module key for %s and can remove it', (label, key) => {
    const view = mount()
    const accessibleLabel = `普通用户显示${label}`
    expect(toggle(view.container, accessibleLabel).getAttribute('aria-checked')).toBe('false')
    click(view.container, accessibleLabel)
    expect(view.onPatch).toHaveBeenLastCalledWith('navigation', { user_visible_modules: [key] })
    expect(toggle(view.container, accessibleLabel).getAttribute('aria-checked')).toBe('true')
    click(view.container, accessibleLabel)
    expect(view.onPatch).toHaveBeenLastCalledWith('navigation', { user_visible_modules: [] })
  })

  it('normalizes duplicates and whitespace in product order without discarding another selected module', () => {
    const view = mount({ navigation: { user_visible_modules: ['prompts', ' commonLines ', 'reports', 'prompts'] } })
    expect(toggle(view.container, '普通用户显示重复内容治理').getAttribute('aria-checked')).toBe('true')
    click(view.container, '普通用户显示知识图谱')
    expect(view.onPatch).toHaveBeenLastCalledWith('navigation', {
      user_visible_modules: ['commonLines', 'knowledgeGraph', 'reports', 'prompts'],
    })
    click(view.container, '普通用户显示重复内容治理')
    expect(view.onPatch).toHaveBeenLastCalledWith('navigation', {
      user_visible_modules: ['knowledgeGraph', 'reports', 'prompts'],
    })
  })

  it('retains the existing empty selection for a null raw navigation input', () => {
    // The backend before-validator accepts None as an empty list; the shared frontend normalizer accepts unknown input.
    const navigation = { user_visible_modules: null } as unknown as NavigationConfig
    const view = mount({ navigation })
    for (const [label] of navigationModules) {
      expect(toggle(view.container, `普通用户显示${label}`).getAttribute('aria-checked')).toBe('false')
    }
    click(view.container, '普通用户显示提示词')
    expect(view.onPatch).toHaveBeenLastCalledWith('navigation', { user_visible_modules: ['prompts'] })
  })
})

describe('observability privacy controls', () => {
  it.each([
    ['切换工具调用结果摘要记录', 'tool_call_log_include_preview'],
    ['切换工作流步骤路径记录', 'agent_log_include_execution_path'],
    ['切换 RAG 指标原文写入', 'metrics_log_include_text'],
  ] as const)('keeps %s independently opt-in', (label, key) => {
    const view = mount()
    expect(toggle(view.container, label).getAttribute('aria-checked')).toBe('false')
    click(view.container, label)
    expect(view.onPatch).toHaveBeenLastCalledWith('observability', { [key]: true })
    click(view.container, label)
    expect(view.onPatch).toHaveBeenLastCalledWith('observability', { [key]: false })
  })

  it('hides disabled tool logging options without clearing their configured preview limit or privacy flag', () => {
    const observability = { ...initialValues().observability, tool_call_log_max_preview_chars: 0 }
    const view = mount({ observability })
    click(view.container, '切换工具调用记录')
    expect(view.onPatch).toHaveBeenLastCalledWith('observability', { tool_call_log_enabled: false })
    expect([...view.container.querySelectorAll('div')].some((node) => node.textContent === '结果摘要最大字符数')).toBe(
      false,
    )
    click(view.container, '切换工具调用记录')
    expect(input(view.container, '结果摘要最大字符数').value).toBe('0')
    expect(toggle(view.container, '切换工具调用结果摘要记录').getAttribute('aria-checked')).toBe('false')
  })
})

describe('runtime controlled configuration', () => {
  it.each([
    ['切换断连自动取消', 'chat', 'stream_cancel_on_disconnect', false],
    ['切换上传去重', 'cache', 'upload_dedup_enabled', false],
    ['切换对话响应缓存', 'cache', 'chat_response_cache_enabled', true],
    ['切换敏感信息脱敏', 'safety', 'pii_redaction_enabled', true],
    ['切换子图编排', 'langgraph', 'use_subgraphs', false],
  ] as const)('emits only the intended field for %s, including explicit false', (label, scope, key, initial) => {
    const view = mount()
    expect(toggle(view.container, label).getAttribute('aria-checked')).toBe(String(initial))
    click(view.container, label)
    expect(view.onPatch).toHaveBeenLastCalledWith(scope, { [key]: !initial })
    click(view.container, label)
    expect(view.onPatch).toHaveBeenLastCalledWith(scope, { [key]: initial })
  })

  it('retains fractional heartbeat and explicit zero payloads and the existing disable hint', () => {
    const view = mount()
    expect(input(view.container, '心跳间隔').value).toBe('0')
    expect(view.container.textContent).toContain('0 表示禁用，不推荐')
    fill(input(view.container, '心跳间隔'), '12.5', 12.5)
    expect(view.onPatch).toHaveBeenLastCalledWith('chat', { stream_heartbeat_sec: 12.5 })
    fill(input(view.container, '心跳间隔'), '', undefined)
    expect(view.onPatch).toHaveBeenLastCalledWith('chat', { stream_heartbeat_sec: 0 })
    expect(input(view.container, '心跳间隔').value).toBe('0')
  })

  it('keeps the empty redaction mask and zero cache budgets through option visibility changes', () => {
    const cache = { ...initialValues().cache, chat_response_cache_ttl_sec: 0, chat_response_cache_max_value_bytes: 0 }
    const view = mount({ cache })
    expect(input(view.container, '脱敏占位符').value).toBe('')
    fill(input(view.container, '脱敏占位符'), 'PRIVATE')
    expect(view.onPatch).toHaveBeenLastCalledWith('safety', { pii_redaction_mask: 'PRIVATE' })
    fill(input(view.container, '脱敏占位符'), '')
    expect(view.onPatch).toHaveBeenLastCalledWith('safety', { pii_redaction_mask: '' })
    click(view.container, '切换对话响应缓存')
    click(view.container, '切换对话响应缓存')
    expect(input(view.container, '缓存时长（秒）').value).toBe('0')
    expect(input(view.container, '最大字节').value).toBe('0')
    expect(toggle(view.container, '切换仅缓存无历史对话').getAttribute('aria-checked')).toBe('false')
    click(view.container, '切换仅缓存无历史对话')
    expect(view.onPatch).toHaveBeenLastCalledWith('cache', { chat_response_cache_require_empty_history: true })
  })
})
