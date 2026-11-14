// @vitest-environment happy-dom

import React, { act, useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { PipelineOptionsProvider } from '@/contexts/pipeline-options-context'
import type { AutoAnnotationResponse, CleanPreviewResponse } from '@/types/processing'
import { queryKeys } from '@/lib/query-keys'
import { waitForAssertion } from '@/test/hook-harness'

import { DataAnnotator, type Annotation } from './data-annotator'
import { DataClassifier } from './data-classifier'
import { DataCleaner } from './data-cleaner'
import { QualityChecker } from './quality-checker'

const boundary = vi.hoisted(() => ({
  governanceAnalyze: vi.fn(),
  autoAnnotations: vi.fn(),
  cleanPreview: vi.fn(),
  llmCleanPreview: vi.fn(),
  listPrompts: vi.fn(),
  warning: vi.fn(),
  success: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
  reportError: vi.fn(),
  reportWarning: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ pipelineApi: boundary, promptTemplateApi: { list: boundary.listPrompts } }))
vi.mock('@/lib/api/pipeline', () => ({ pipelineApi: boundary }))
vi.mock('@/lib/api/prompts', () => ({ promptTemplateApi: { list: boundary.listPrompts } }))
vi.mock('@/lib/client-logging', () => ({
  reportClientError: boundary.reportError,
  reportClientWarning: boundary.reportWarning,
}))
vi.mock('sonner', () => ({
  toast: { warning: boundary.warning, success: boundary.success, info: boundary.info, error: boundary.error },
}))
vi.mock('next-intl', () => {
  const translations = new Map<string, ReturnType<typeof makeTranslation>>()
  function makeTranslation(namespace: string) {
    return Object.assign((key: string) => `${namespace}.${key}`, { raw: () => ['Preset tag'] })
  }
  return {
    useTranslations: (namespace: string) => {
      if (!translations.has(namespace)) translations.set(namespace, makeTranslation(namespace))
      return translations.get(namespace)
    },
  }
})
vi.mock('@/components/pipeline-options-panel', () => ({ PipelineOptionsPanel: () => null }))
vi.mock('@/components/governance-profile-selector', () => ({ GovernanceProfileSelector: () => null }))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((accept, fail) => {
    resolve = accept
    reject = fail
  })
  return { promise, resolve, reject }
}

function annotationResponse(overrides: Partial<AutoAnnotationResponse> = {}): AutoAnnotationResponse {
  return {
    annotations: [],
    document_tags: [],
    text_chars: 5,
    scanned_chars: 5,
    truncated: false,
    strategy: 'rules',
    providers_used: ['cpu'],
    warnings: [],
    ...overrides,
  }
}

function cleanResponse(markdown = 'Cleaned text'): CleanPreviewResponse {
  return { markdown, applied_rules: 1, changed: true }
}

const cleanups = new Set<() => void>()
const emptyAnnotations: Annotation[] = []
const emptyTags: string[] = []
const emptyIssues: [] = []

function renderTool(element: React.ReactNode, strict = false) {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const render = async (next: React.ReactNode) => {
    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <PipelineOptionsProvider>
            {strict ? <React.StrictMode>{next}</React.StrictMode> : next}
          </PipelineOptionsProvider>
        </QueryClientProvider>,
      )
    })
  }
  const unmount = () => {
    act(() => root.unmount())
    client.clear()
    container.remove()
    cleanups.delete(unmount)
  }
  cleanups.add(unmount)
  return { container, render, unmount, client, ready: render(element) }
}

function button(container: HTMLElement, text: string) {
  const match =
    [...container.querySelectorAll<HTMLButtonElement>('button, summary')].find((item) =>
      item.textContent?.includes(text),
    ) ??
    [...container.querySelectorAll('label')]
      .find((item) => item.textContent?.includes(text))
      ?.querySelector<HTMLInputElement>('input')
  expect(match, `button ${text}`).toBeDefined()
  return match!
}

async function click(container: HTMLElement, text: string) {
  await act(async () => button(container, text).click())
}

beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  boundary.listPrompts.mockResolvedValue({ total: 0, items: [] })
  boundary.governanceAnalyze.mockResolvedValue({ issues: [] })
  boundary.autoAnnotations.mockResolvedValue(annotationResponse())
  boundary.cleanPreview.mockResolvedValue(cleanResponse())
  boundary.llmCleanPreview.mockResolvedValue({ markdown: 'LLM cleaned', changed: true, warnings: [] })
})

afterEach(() => {
  for (const cleanup of cleanups) cleanup()
  cleanups.clear()
  vi.restoreAllMocks()
  globalThis.getSelection()?.removeAllRanges()
  document.body.replaceChildren()
})

const asyncTools = [
  {
    name: 'quality',
    action: '开始检测',
    busy: '正在检测…',
    request: boundary.governanceAnalyze,
  },
  {
    name: 'cleaner',
    action: '运行清洗',
    busy: '正在清洗…',
    request: boundary.cleanPreview,
  },
  {
    name: 'classifier',
    action: '自动分类',
    busy: '正在分类…',
    request: boundary.autoAnnotations,
  },
  {
    name: 'annotator',
    action: '自动标注',
    busy: '正在标注…',
    request: boundary.autoAnnotations,
  },
] as const

function QualityHarness({ content, publish }: { content: string; publish: (...values: unknown[]) => void }) {
  const [result, setResult] = useState<Parameters<React.ComponentProps<typeof QualityChecker>['onComplete']>[0] | null>(
    null,
  )
  return (
    <QualityChecker
      content={content}
      initialScore={result?.score ?? 25}
      initialIssues={result?.issues ?? emptyIssues}
      checked={Boolean(result)}
      onComplete={(next) => {
        setResult(next)
        publish(next)
      }}
    />
  )
}

function toolElement(
  name: (typeof asyncTools)[number]['name'],
  content: string,
  publish: (...values: unknown[]) => void,
  fileId = 'file-a',
) {
  if (name === 'quality') {
    return <QualityHarness key={fileId} content={content} publish={publish} />
  }
  if (name === 'cleaner') return <DataCleaner key={fileId} content={content} onClean={publish} />
  if (name === 'classifier') {
    return <DataClassifier key={fileId} content={content} initialTags={emptyTags} onClassify={publish} />
  }
  return <DataAnnotator key={fileId} content={content} annotations={emptyAnnotations} onAnnotate={publish} />
}

function resultFor(name: (typeof asyncTools)[number]['name']) {
  if (name === 'quality') return { issues: [] }
  if (name === 'cleaner') return cleanResponse()
  return annotationResponse({
    annotations: [
      { text: 'Alpha', type: 'keyword', label: 'Old annotation', start: 0, end: 5, confidence: 0.8, source: 'cpu' },
    ],
    document_tags: [{ type: 'category', value: 'Old category', label: 'Old category', confidence: 0.8, source: 'cpu' }],
  })
}

describe.each(asyncTools)('$name async ownership', ({ name, action, busy, request }) => {
  it('publishes a current successful request', async () => {
    const publish = vi.fn()
    request.mockResolvedValue(resultFor(name))
    const view = renderTool(toolElement(name, 'Alpha source', publish))
    await view.ready
    await click(view.container, action)

    expect(request).toHaveBeenCalledTimes(1)
    expect(publish).toHaveBeenCalledTimes(1)
  })

  it('ignores a completion after switching files with identical text', async () => {
    const pending = deferred<ReturnType<typeof resultFor>>()
    request.mockReturnValue(pending.promise)
    const oldPublish = vi.fn()
    const newPublish = vi.fn()
    const view = renderTool(toolElement(name, 'Alpha source', oldPublish))
    await view.ready
    await click(view.container, action)
    await view.render(toolElement(name, 'Alpha source', newPublish, 'file-b'))

    await act(async () => pending.resolve(resultFor(name)))

    expect(oldPublish).not.toHaveBeenCalled()
    expect(newPublish).not.toHaveBeenCalled()
    expect(view.container.textContent).not.toContain('Old category')
    expect(view.container.textContent).not.toContain('Old annotation')
    expect(button(view.container, action).disabled).toBe(false)
  })

  it('does not publish an old request after leaving and returning to its content', async () => {
    const pending = deferred<ReturnType<typeof resultFor>>()
    request.mockReturnValue(pending.promise)
    const publish = vi.fn()
    const view = renderTool(toolElement(name, 'Alpha source', publish))
    await view.ready
    await click(view.container, action)
    await view.render(toolElement(name, 'Beta source', publish, 'file-b'))
    await view.render(toolElement(name, 'Alpha source', publish, 'file-a'))

    await act(async () => pending.resolve(resultFor(name)))

    expect(publish).not.toHaveBeenCalled()
  })

  it('does not publish after unmount', async () => {
    const pending = deferred<ReturnType<typeof resultFor>>()
    request.mockReturnValue(pending.promise)
    const publish = vi.fn()
    const view = renderTool(toolElement(name, 'Alpha source', publish))
    await view.ready
    await click(view.container, action)
    view.unmount()

    await act(async () => pending.resolve(resultFor(name)))

    expect(publish).not.toHaveBeenCalled()
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('keeps a new request busy when an obsolete request fails', async () => {
    const oldRequest = deferred<ReturnType<typeof resultFor>>()
    const currentRequest = deferred<ReturnType<typeof resultFor>>()
    request.mockReturnValueOnce(oldRequest.promise).mockReturnValueOnce(currentRequest.promise)
    const oldPublish = vi.fn()
    const currentPublish = vi.fn()
    const view = renderTool(toolElement(name, 'Alpha source', oldPublish))
    await view.ready
    await click(view.container, action)
    await view.render(toolElement(name, 'Beta source', currentPublish, 'file-b'))
    await click(view.container, action)

    await act(async () => oldRequest.reject(new Error('Obsolete request')))
    expect(button(view.container, busy).disabled).toBe(true)
    expect(boundary.error).not.toHaveBeenCalled()
    expect(view.container.textContent).not.toContain('Obsolete request')
    await act(async () => currentRequest.resolve(resultFor(name)))

    expect(oldPublish).not.toHaveBeenCalled()
    expect(currentPublish).toHaveBeenCalledTimes(1)
  })

  it('keeps the existing current-request failure policy', async () => {
    const publish = vi.fn()
    request.mockRejectedValue(new Error('Current request failed'))
    const view = renderTool(toolElement(name, 'Alpha source', publish))
    await view.ready
    await click(view.container, action)

    if (name === 'quality') {
      expect(publish).not.toHaveBeenCalled()
      expect(boundary.error).toHaveBeenCalled()
      expect(boundary.reportError).toHaveBeenCalledTimes(1)
    } else {
      expect(publish).not.toHaveBeenCalled()
      if (name === 'cleaner')
        expect(boundary.error).toHaveBeenCalledWith(
          expect.stringContaining('Current request failed'),
          expect.anything(),
        )
      else expect(boundary.error).toHaveBeenCalledTimes(1)
    }
    expect(button(view.container, action).disabled).toBe(false)
  })

  it('keeps current work through callback recreation and uses the latest callback', async () => {
    const pending = deferred<ReturnType<typeof resultFor>>()
    request.mockReturnValue(pending.promise)
    const oldPublish = vi.fn()
    const currentPublish = vi.fn()
    const view = renderTool(toolElement(name, 'Alpha source', oldPublish))
    await view.ready
    await click(view.container, action)

    await view.render(toolElement(name, 'Alpha source', currentPublish))

    expect(button(view.container, busy).disabled).toBe(true)
    expect(request).toHaveBeenCalledTimes(1)
    await act(async () => pending.resolve(resultFor(name)))
    expect(currentPublish).toHaveBeenCalledTimes(1)
    expect(oldPublish).not.toHaveBeenCalled()
  })

  it('keeps completed current-session state when only its callback changes', async () => {
    const oldPublish = vi.fn()
    const currentPublish = vi.fn()
    const expected = name === 'quality' ? '100' : name === 'cleaner' ? 'Retained preview' : 'Old category'
    request.mockResolvedValue(name === 'cleaner' ? { ...cleanResponse(), diff_unified: expected } : resultFor(name))
    const view = renderTool(toolElement(name, 'Alpha source', oldPublish))
    await view.ready
    await click(view.container, action)
    if (name === 'cleaner') await click(view.container, '查看文本差异')
    expect(view.container.textContent).toContain(expected)

    await view.render(toolElement(name, 'Alpha source', currentPublish))

    expect(view.container.textContent).toContain(expected)
    expect(oldPublish).toHaveBeenCalledTimes(1)
    expect(currentPublish).not.toHaveBeenCalled()
  })
})

describe('tool editing and multi-stage operations', () => {
  it('keeps explicit quality scanning idle through callback changes and uses the latest callback', async () => {
    const pending = deferred<{ issues: [] }>()
    boundary.governanceAnalyze.mockReturnValue(pending.promise)
    const oldPublish = vi.fn()
    const currentPublish = vi.fn()
    const view = renderTool(
      <QualityChecker key="file-a" content="Alpha" initialIssues={emptyIssues} onComplete={oldPublish} />,
    )
    await view.ready
    expect(boundary.governanceAnalyze).not.toHaveBeenCalled()

    await view.render(
      <QualityChecker key="file-a" content="Alpha" initialIssues={emptyIssues} onComplete={currentPublish} />,
    )

    expect(boundary.governanceAnalyze).not.toHaveBeenCalled()
    await click(view.container, '开始检测')
    expect(boundary.governanceAnalyze).toHaveBeenCalledTimes(1)
    await act(async () => pending.resolve({ issues: [] }))
    expect(currentPublish).toHaveBeenCalledTimes(1)
    expect(oldPublish).not.toHaveBeenCalled()
  })

  it('selects an active prompt after the first page without sharing the chat page cache', async () => {
    const templates = Array.from({ length: 51 }, (_, index) => ({
      id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, '0')}`,
      name: `Template ${index + 1}`,
    }))
    boundary.listPrompts.mockImplementation(({ skip = 0 }: { skip?: number }) =>
      Promise.resolve({ total: templates.length, items: templates.slice(skip, skip + 50) }),
    )
    const view = renderTool(<DataCleaner content="Original" onClean={vi.fn()} />)
    await view.ready
    const chatPageKey = queryKeys.prompts.list({ is_active: true, limit: 50 })
    await act(async () => {
      view.client.setQueryData(chatPageKey, templates.slice(0, 50))
    })
    await click(view.container, '模型二次清洗')
    const select = view.container.querySelector<HTMLSelectElement>('select[aria-label="清洗提示词模板"]')!
    await waitForAssertion(() => {
      expect(Array.from(select.options).some((option) => option.textContent === 'Template 51')).toBe(true)
    })
    await act(async () => {
      select.value = templates[50].id
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await click(view.container, '运行清洗')

    expect(boundary.llmCleanPreview.mock.calls[0][0].prompt_template_id).toBe(templates[50].id)
    expect(view.client.getQueryData(chatPageKey)).toEqual(templates.slice(0, 50))
  })

  it('does not request more prompt pages after unmount', async () => {
    const pending = deferred<{ total: number; items: Array<{ id: string; name: string }> }>()
    boundary.listPrompts.mockReturnValue(pending.promise)
    const view = renderTool(<DataCleaner content="Original" onClean={vi.fn()} />)
    await view.ready
    view.unmount()

    await act(async () => {
      pending.resolve({ total: 2, items: [{ id: 'first', name: 'First' }] })
    })

    expect(boundary.listPrompts).toHaveBeenCalledTimes(1)
  })

  it('rejects pending cleaning after an external draft edit', async () => {
    const pending = deferred<CleanPreviewResponse>()
    boundary.cleanPreview.mockReturnValue(pending.promise)
    const publish = vi.fn()
    const view = renderTool(<DataCleaner content="Original" cleanedContent="Original" onClean={publish} />)
    await view.ready
    await click(view.container, '运行清洗')
    await view.render(<DataCleaner content="Original" cleanedContent="Manual edit" onClean={publish} />)

    await act(async () => pending.resolve(cleanResponse()))

    expect(publish).not.toHaveBeenCalled()
  })

  it('rejects pending classification after an external metadata reset', async () => {
    const pending = deferred<AutoAnnotationResponse>()
    boundary.autoAnnotations.mockReturnValue(pending.promise)
    const publish = vi.fn()
    const initialTags = ['Tag A']
    const view = renderTool(
      <DataClassifier content="Alpha" initialCategory="Category A" initialTags={initialTags} onClassify={publish} />,
    )
    await view.ready
    await click(view.container, '自动分类')
    await view.render(
      <DataClassifier content="Alpha" initialCategory={null} initialTags={emptyTags} onClassify={publish} />,
    )

    await act(async () => pending.resolve(resultFor('classifier') as AutoAnnotationResponse))

    expect(publish).not.toHaveBeenCalled()
  })

  it('rejects pending annotation after an external annotation reset', async () => {
    const pending = deferred<AutoAnnotationResponse>()
    boundary.autoAnnotations.mockReturnValue(pending.promise)
    const publish = vi.fn()
    const initial: Annotation[] = [{ id: 'one', type: 'keyword', text: 'Alpha', label: 'Keyword', start: 0, end: 5 }]
    const view = renderTool(<DataAnnotator content="Alpha" annotations={initial} onAnnotate={publish} />)
    await view.ready
    await click(view.container, '自动标注')
    await view.render(<DataAnnotator content="Alpha" annotations={emptyAnnotations} onAnnotate={publish} />)

    await act(async () => pending.resolve(resultFor('annotator') as AutoAnnotationResponse))

    expect(publish).not.toHaveBeenCalled()
  })

  it('keeps its preview when the parent acknowledges a successful clean', async () => {
    boundary.cleanPreview.mockResolvedValue({ ...cleanResponse(), diff_unified: 'Confirmed diff' })
    function Parent() {
      const [cleanedContent, setCleanedContent] = useState('Original')
      return <DataCleaner content="Original" cleanedContent={cleanedContent} onClean={setCleanedContent} />
    }
    const view = renderTool(<Parent />)
    await view.ready
    await click(view.container, '运行清洗')
    await click(view.container, '查看文本差异')

    expect(view.container.textContent).toContain('Confirmed diff')
  })

  it('keeps suggestions when the parent acknowledges automatic classification', async () => {
    boundary.autoAnnotations.mockResolvedValue(resultFor('classifier'))
    function Parent() {
      const [data, setData] = useState<{ category: string | null; tags: string[] }>({ category: null, tags: [] })
      const classify = useCallback((category: string, tags: string[]) => setData({ category, tags }), [])
      return (
        <DataClassifier content="Alpha" initialCategory={data.category} initialTags={data.tags} onClassify={classify} />
      )
    }
    const view = renderTool(<Parent />)
    await view.ready
    await click(view.container, '自动分类')

    expect(view.container.textContent).toContain('推荐标签')
    expect(view.container.textContent).toContain('Old category')
  })

  it('keeps an explicit cleaner reset from being overwritten by pending cleaning', async () => {
    const pending = deferred<CleanPreviewResponse>()
    boundary.cleanPreview.mockReturnValue(pending.promise)
    const onClean = vi.fn()
    const view = renderTool(<DataCleaner content="Original text" onClean={onClean} />)
    await view.ready
    await click(view.container, '运行清洗')
    await view.render(<DataCleaner content="Original text" resetRevision={1} onClean={onClean} />)

    await act(async () => pending.resolve(cleanResponse()))

    expect(onClean).not.toHaveBeenCalled()
  })

  it('does not start LLM cleaning for a preview that belongs to the previous file', async () => {
    const pending = deferred<CleanPreviewResponse>()
    boundary.cleanPreview.mockReturnValue(pending.promise)
    const oldClean = vi.fn()
    const view = renderTool(<DataCleaner key="file-a" content="Alpha source" onClean={oldClean} />)
    await view.ready
    await click(view.container, '模型二次清洗')
    await click(view.container, '运行清洗')
    await view.render(<DataCleaner key="file-b" content="Beta source" onClean={vi.fn()} />)

    await act(async () => pending.resolve(cleanResponse()))

    expect(boundary.llmCleanPreview).not.toHaveBeenCalled()
    expect(oldClean).not.toHaveBeenCalled()
  })

  it('retains the rule result when current LLM cleaning fails', async () => {
    boundary.llmCleanPreview.mockRejectedValue(new Error('LLM unavailable'))
    const onClean = vi.fn()
    const view = renderTool(<DataCleaner content="Original text" onClean={onClean} />)
    await view.ready
    await click(view.container, '模型二次清洗')
    await click(view.container, '运行清洗')

    expect(onClean).toHaveBeenCalledExactlyOnceWith('Cleaned text')
    expect(boundary.error).toHaveBeenCalledWith(expect.stringContaining('LLM unavailable'), expect.anything())
  })

  it('synchronizes classifier state to the next file without publishing it as an edit', async () => {
    const onClassify = vi.fn()
    const view = renderTool(
      <DataClassifier
        key="file-a"
        content="Alpha"
        initialCategory="Category A"
        initialTags={['Tag A']}
        onClassify={onClassify}
      />,
    )
    await view.ready
    await view.render(
      <DataClassifier
        key="file-b"
        content="Beta"
        initialCategory="Category B"
        initialTags={['Tag B']}
        onClassify={onClassify}
      />,
    )

    expect(view.container.textContent).toContain('Category B')
    expect(view.container.textContent).toContain('Tag B')
    expect(view.container.textContent).not.toContain('Tag A')
    expect(onClassify).not.toHaveBeenCalled()
  })

  it('does not overwrite a newer manual classification edit', async () => {
    const pending = deferred<AutoAnnotationResponse>()
    boundary.autoAnnotations.mockReturnValue(pending.promise)
    const publish = vi.fn()
    const view = renderTool(<DataClassifier content="Alpha" initialTags={emptyTags} onClassify={publish} />)
    await view.ready
    await click(view.container, '自动分类')
    await click(view.container, 'Preset tag')
    await act(async () => pending.resolve(resultFor('classifier') as AutoAnnotationResponse))

    expect(publish).toHaveBeenCalledExactlyOnceWith('', ['Preset tag'])
    expect(boundary.success).not.toHaveBeenCalled()
  })

  it('publishes manual annotation deletion once under Strict Mode', async () => {
    const publish = vi.fn()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const initial: Annotation[] = [{ id: 'one', type: 'keyword', text: 'Alpha', label: 'Keyword', start: 0, end: 5 }]
    function Parent() {
      const [annotations, setAnnotations] = useState(initial)
      const onAnnotate = useCallback((next: Annotation[]) => {
        publish(next)
        setAnnotations(next)
      }, [])
      return <DataAnnotator content="Alpha" annotations={annotations} onAnnotate={onAnnotate} />
    }
    const view = renderTool(<Parent />, true)
    await view.ready
    const remove = view.container.querySelector<HTMLButtonElement>('button[aria-label="删除标注 Alpha"]')!
    expect(remove).not.toBeNull()
    await act(async () => remove.click())

    expect(publish).toHaveBeenCalledExactlyOnceWith([])
    expect(console.error).not.toHaveBeenCalled()
  })

  it('keeps automatic annotation offsets relative to the displayed untrimmed content', async () => {
    const content = ' \n Alpha beta  '
    boundary.autoAnnotations.mockResolvedValue(
      annotationResponse({
        annotations: [
          { text: 'Alpha', type: 'keyword', label: 'Keyword', start: 0, end: 5, confidence: 0.8, source: 'cpu' },
        ],
      }),
    )
    const publish = vi.fn()
    const view = renderTool(<DataAnnotator content={content} annotations={emptyAnnotations} onAnnotate={publish} />)
    await view.ready
    await click(view.container, '自动标注')

    const annotation = publish.mock.calls[0][0][0] as Annotation
    expect(content.slice(annotation.start, annotation.end)).toBe(annotation.text)
    expect(annotation.start).toBe(content.indexOf('Alpha'))
    expect(boundary.autoAnnotations.mock.calls[0][0].text).toBe(content.trim())
  })

  it('converts Python Unicode offsets to the displayed UTF-16 range', async () => {
    const content = '\n 😀 Alpha beta'
    boundary.autoAnnotations.mockResolvedValue(
      annotationResponse({
        annotations: [
          { text: 'Alpha', type: 'keyword', label: 'Keyword', start: 2, end: 7, confidence: 0.8, source: 'cpu' },
        ],
      }),
    )
    const publish = vi.fn()
    const view = renderTool(<DataAnnotator content={content} annotations={emptyAnnotations} onAnnotate={publish} />)
    await view.ready
    await click(view.container, '自动标注')

    const annotation = publish.mock.calls[0][0][0] as Annotation
    expect(annotation.start).toBe(content.indexOf('Alpha'))
    expect(content.slice(annotation.start, annotation.end)).toBe('Alpha')
  })

  it.each([
    { content: '\n\nprefix  Alpha    beta trailing', selectedText: 'Alpha beta', originalText: 'Alpha    beta' },
    { content: '\n\nprefix  a+b   c[d] trailing', selectedText: 'a+b c[d]', originalText: 'a+b   c[d]' },
  ])(
    'maps normalized DOM selection $selectedText back to original whitespace offsets',
    async ({ content, selectedText, originalText }) => {
      const preview = document.createElement('div')
      preview.dataset.governanceSelectionRoot = 'true'
      preview.textContent = selectedText
      document.body.appendChild(preview)
      const publish = vi.fn()
      const view = renderTool(<DataAnnotator content={content} annotations={emptyAnnotations} onAnnotate={publish} />)
      await view.ready
      await click(view.container, '选择正文文字')
      const range = document.createRange()
      range.selectNodeContents(preview)
      const selection = globalThis.getSelection()!
      selection.removeAllRanges()
      selection.addRange(range)
      await act(async () => document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true })))
      await click(view.container, '添加DataAnnotator.types.keyword.label标注')

      const annotation = publish.mock.calls[0][0][0] as Annotation
      expect(annotation.start).toBe(content.indexOf(originalText))
      expect(content.slice(annotation.start, annotation.end)).toBe(annotation.text)
      expect(annotation.text).toBe(originalText)
    },
  )

  it('clears a captured selection when non-empty content changes', async () => {
    const preview = document.createElement('div')
    preview.dataset.governanceSelectionRoot = 'true'
    preview.textContent = 'Alpha'
    document.body.appendChild(preview)
    const publish = vi.fn()
    const view = renderTool(<DataAnnotator content="Alpha" annotations={emptyAnnotations} onAnnotate={publish} />)
    await view.ready
    await click(view.container, '选择正文文字')
    const range = document.createRange()
    range.selectNodeContents(preview)
    const selection = globalThis.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)
    await act(async () => {
      document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    })
    expect(view.container.textContent).toContain('添加DataAnnotator.types.keyword.label标注')

    await view.render(<DataAnnotator content="Beta" annotations={emptyAnnotations} onAnnotate={publish} />)

    expect(view.container.textContent).not.toContain('添加DataAnnotator.types.keyword.label标注')
    expect(publish).not.toHaveBeenCalled()
  })
})
