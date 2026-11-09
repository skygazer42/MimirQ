// @vitest-environment happy-dom

import React, { act, useEffect, useState } from 'react'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { NextIntlClientProvider } from 'next-intl'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Conversation, Dataset, RegressionCase, TestGenResponse } from '@/types'

const controlled = vi.hoisted(() => ({
  api: {
    evaluationApi: {
      listRegressionCases: vi.fn(),
      listRegressionRuns: vi.fn(),
      generateFromDocuments: vi.fn(),
      generateFromConversations: vi.fn(),
    },
    documentApi: { list: vi.fn() },
    datasetApi: { listAll: vi.fn() },
    chatApi: { listConversations: vi.fn() },
    ragApi: { retrieveEvidence: vi.fn() },
  },
  toast: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('@/lib/api', () => controlled.api)
vi.mock('sonner', () => ({ toast: controlled.toast }))

import { QueryProvider } from '@/components/providers/query-provider'
import { evaluationApi } from '@/lib/api'
import { AUTH_SCOPE_CHANGED_EVENT } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { TestCaseManager } from './test-case-manager'
import { TestGenerationDialog } from './test-generation-dialog'

const DATASET_A = '11111111-1111-4111-8111-111111111111'
const DATASET_B = '22222222-2222-4222-8222-222222222222'
const DOC_A = '33333333-3333-4333-8333-333333333333'
const DOC_B = '44444444-4444-4444-8444-444444444444'
const CASE_A = '55555555-5555-4555-8555-555555555555'
const CONVERSATION_A = '66666666-6666-4666-8666-666666666666'
const DOCS_A = [DOC_A]
const DOCS_B = [DOC_B]
let capturedClient: QueryClient

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: Error) => void
  const promise = new Promise<T>((fulfill, fail) => {
    resolve = fulfill
    reject = fail
  })
  return { promise, resolve, reject }
}

function result(
  question: string,
  savedCaseIds: string[] = [],
  sourceId = DOC_A,
  sourceType: 'document' | 'conversation' = 'document',
): TestGenResponse {
  return {
    status: 'completed',
    generated_questions: [{ question, source_type: sourceType, source_id: sourceId, metadata: {} }],
    saved_case_ids: savedCaseIds,
  }
}

function savedCase(question: string): RegressionCase {
  return {
    id: CASE_A,
    tenant_id: DATASET_A,
    dataset_id: DATASET_A,
    document_ids: [DOC_A],
    question,
    expected_answer: 'A supported expected answer',
    reference_sources: [{ document_id: DOC_A, chunk_id: CASE_A }],
    tags: ['golden_draft'],
    extra: {},
    created_at: '2026-11-05T12:00:00Z',
    updated_at: '2026-11-05T12:00:00Z',
  }
}

function CaptureClient() {
  const client = useQueryClient()
  useEffect(() => {
    capturedClient = client
  }, [client])
  return null
}

function RunHistory() {
  const query = useQuery({
    queryKey: queryKeys.evaluations.regressionRuns({ limit: 50 }),
    queryFn: () => evaluationApi.listRegressionRuns({ limit: 50 }),
  })
  return <output>{query.data?.items?.length ?? 0} runs</output>
}

function GenerationSurface({ conversation = false }: Readonly<{ conversation?: boolean }>) {
  const [open, setOpen] = useState(true)
  const [session, setSession] = useState<'a' | 'b'>('a')
  return (
    <>
      <CaptureClient />
      <section aria-label="Case library">
        <TestCaseManager datasetId={DATASET_A} />
      </section>
      <RunHistory />
      <button
        type="button"
        onClick={() => {
          setSession('a')
          setOpen(true)
        }}
      >
        Open A
      </button>
      <button
        type="button"
        onClick={() => {
          setSession('b')
          setOpen(true)
        }}
      >
        Open B
      </button>
      <TestGenerationDialog
        open={open}
        onClose={() => setOpen(false)}
        initialSourceType={conversation ? 'conversations' : 'documents'}
        initialDatasetId={conversation ? undefined : session === 'a' ? DATASET_A : DATASET_B}
        initialDocumentIds={conversation ? undefined : session === 'a' ? DOCS_A : DOCS_B}
      />
    </>
  )
}

describe('test generation session and persisted case ownership through actual React DOM', () => {
  let container: HTMLDivElement
  let root: ReturnType<typeof createRoot>
  let serverCases: RegressionCase[]

  beforeEach(() => {
    vi.resetAllMocks()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Unexpected HTTP in controlled test')))
    ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    serverCases = []
    controlled.api.evaluationApi.listRegressionCases.mockImplementation(async () => ({
      total: serverCases.length,
      items: [...serverCases],
    }))
    controlled.api.evaluationApi.listRegressionRuns.mockResolvedValue({ total: 0, items: [] })
    controlled.api.evaluationApi.generateFromDocuments.mockResolvedValue(result('Current generated question'))
    controlled.api.evaluationApi.generateFromConversations.mockResolvedValue(
      result('Conversation generated question', [], CONVERSATION_A, 'conversation'),
    )
    controlled.api.documentApi.list.mockResolvedValue({ total: 0, items: [] })
    controlled.api.datasetApi.listAll.mockResolvedValue([
      { id: DATASET_A, name: 'Dataset A', tenant_id: DATASET_A, permission: 'all_team_members' },
      { id: DATASET_B, name: 'Dataset B', tenant_id: DATASET_A, permission: 'all_team_members' },
    ] satisfies Dataset[])
    controlled.api.chatApi.listConversations.mockResolvedValue({
      total: 1,
      items: [
        {
          id: CONVERSATION_A,
          title: 'Conversation A',
          message_count: 2,
          created_at: '2026-11-05T12:00:00Z',
          updated_at: '2026-11-05T12:00:00Z',
        } satisfies Conversation,
      ],
    })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    capturedClient.clear()
    document.body.innerHTML = ''
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function button(text: string): HTMLButtonElement {
    return Array.from(document.querySelectorAll('button')).find((element) => element.textContent?.trim() === text)!
  }

  function generationButton(): HTMLButtonElement {
    const control = button('开始生成') ?? button('生成中...')
    expect(control).toBeDefined()
    return control
  }

  function dialog() {
    return document.querySelector('[role="dialog"]') as HTMLDivElement
  }

  function library() {
    return container.querySelector('[aria-label="Case library"]') as HTMLElement
  }

  async function mount(conversation = false) {
    act(() =>
      root.render(
        <NextIntlClientProvider
          locale="en"
          timeZone="UTC"
          messages={{ CommonUi: { confirmDialog: { cancel: 'Cancel', confirm: 'Confirm' } } }}
        >
          <QueryProvider>
            <GenerationSurface conversation={conversation} />
          </QueryProvider>
        </NextIntlClientProvider>,
      ),
    )
    await act(async () => {
      await vi.waitFor(() =>
        expect(
          capturedClient.getQueryState(
            queryKeys.evaluations.regressionCases({ limit: 200, fetch_max: 1000, dataset_id: DATASET_A }),
          )?.status,
        ).toBe('success'),
      )
    })
    expect(controlled.api.evaluationApi.listRegressionRuns).toHaveBeenCalledOnce()
  }

  function start() {
    act(() => generationButton().click())
  }

  function closeAndOpenB() {
    act(() => button('Close').click())
    expect(dialog()).toBeNull()
    act(() => button('Open B').click())
    expect(dialog()).not.toBeNull()
  }

  it('keeps a reopened dialog in its new source flow after an older generation completes', async () => {
    const older = deferred<TestGenResponse>()
    controlled.api.evaluationApi.generateFromDocuments.mockReturnValueOnce(older.promise)
    await mount()
    start()
    closeAndOpenB()
    await act(async () => older.resolve(result('Retired session question')))

    expect(dialog().textContent).toContain('配置生成参数')
    expect(dialog().textContent).not.toContain('Retired session question')
    expect(generationButton().disabled).toBe(false)
  })

  it('does not place an older request error into the reopened dialog', async () => {
    const older = deferred<TestGenResponse>()
    controlled.api.evaluationApi.generateFromDocuments.mockReturnValueOnce(older.promise)
    await mount()
    start()
    closeAndOpenB()
    await act(async () => older.reject(new Error('Retired generation failed')))

    expect(dialog().textContent).not.toContain('Retired generation failed')
    expect(dialog().textContent).not.toContain('生成问题失败')
    expect(generationButton().disabled).toBe(false)
  })

  it('allows the new session to generate and keeps its busy flag when the older request finishes', async () => {
    const older = deferred<TestGenResponse>()
    const current = deferred<TestGenResponse>()
    controlled.api.evaluationApi.generateFromDocuments
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(current.promise)
    await mount()
    start()
    closeAndOpenB()
    expect(generationButton().disabled).toBe(false)
    start()
    expect(controlled.api.evaluationApi.generateFromDocuments).toHaveBeenCalledTimes(2)
    await act(async () => older.resolve(result('Retired session question')))
    expect(generationButton().disabled).toBe(true)
    expect(dialog().textContent).not.toContain('Retired session question')
    await act(async () => current.resolve(result('Current session question', [], DOC_B)))
    expect(dialog().textContent).toContain('Current session question')
  })

  it('refreshes the actual case library after persisted generation without refetching unrelated runs', async () => {
    const generation = deferred<TestGenResponse>()
    controlled.api.evaluationApi.generateFromDocuments.mockReturnValueOnce(generation.promise)
    await mount()
    start()
    serverCases = [savedCase('Persisted generated case')]
    await act(async () => generation.resolve(result('Persisted generated case', [CASE_A])))
    await act(async () => {
      await vi.waitFor(() => expect(library().textContent).toContain('Persisted generated case'))
    })
    expect(controlled.api.evaluationApi.listRegressionRuns).toHaveBeenCalledOnce()
    expect(controlled.api.evaluationApi.generateFromDocuments).toHaveBeenCalledExactlyOnceWith({
      dataset_id: DATASET_A,
      document_ids: [DOC_A],
      num_questions: 10,
      question_types: ['factual', 'multi_hop', 'comparison'],
      auto_save_as_cases: true,
    })
  })

  it('refreshes persisted cases after ordinary dialog close while keeping the reopened preview untouched', async () => {
    const older = deferred<TestGenResponse>()
    controlled.api.evaluationApi.generateFromDocuments.mockReturnValueOnce(older.promise)
    await mount()
    start()
    closeAndOpenB()
    serverCases = [savedCase('Background saved case')]
    await act(async () => older.resolve(result('Background saved case', [CASE_A])))
    await act(async () => {
      await vi.waitFor(() => expect(library().textContent).toContain('Background saved case'))
    })
    expect(dialog().textContent).not.toContain('Background saved case')
    expect(dialog().textContent).toContain('配置生成参数')
    expect(controlled.toast.success).toHaveBeenCalledWith('成功生成 1 个问题，已保存 1 个用例')
    expect(controlled.api.evaluationApi.listRegressionRuns).toHaveBeenCalledOnce()
  })

  it.each(['success', 'failure'] as const)(
    'retires old %s publication when the real auth-scope event removes its query owner',
    async (outcome) => {
      const older = deferred<TestGenResponse>()
      controlled.api.evaluationApi.generateFromDocuments.mockReturnValueOnce(older.promise)
      await mount()
      const sourceKey = queryKeys.documents.list({ limit: 100, status: 'completed' })
      const previousOwner = capturedClient.getQueryCache().find({ queryKey: sourceKey, exact: true })
      expect(previousOwner).toBeDefined()
      start()
      act(() => window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT)))
      expect(capturedClient.getQueryCache().find({ queryKey: sourceKey, exact: true })).not.toBe(previousOwner)
      await act(async () => {
        if (outcome === 'success') older.resolve(result('Retired query scope question'))
        else older.reject(new Error('Retired query scope failure'))
      })
      expect(dialog().textContent).not.toContain('Retired query scope')
      expect(controlled.toast.success).not.toHaveBeenCalled()
      expect(controlled.toast.error).not.toHaveBeenCalled()

      start()
      await act(async () => {
        await vi.waitFor(() => expect(controlled.api.evaluationApi.generateFromDocuments).toHaveBeenCalledTimes(2))
      })
      expect(dialog().textContent).toContain('Current generated question')
    },
  )

  it('keeps preview-only document generation out of the persisted case cache', async () => {
    await mount()
    act(() => (dialog().querySelector('[role="switch"]') as HTMLButtonElement).click())
    start()
    await act(async () => {
      await vi.waitFor(() => expect(controlled.api.evaluationApi.generateFromDocuments).toHaveBeenCalled())
    })
    expect(dialog().textContent).toContain('Current generated question')
    expect(controlled.api.evaluationApi.generateFromDocuments).toHaveBeenLastCalledWith(
      expect.objectContaining({ auto_save_as_cases: false }),
    )
    expect(controlled.api.evaluationApi.listRegressionCases).toHaveBeenCalledOnce()
    expect(controlled.api.evaluationApi.listRegressionRuns).toHaveBeenCalledOnce()
  })

  it('preserves the actual conversation request and current completed preview', async () => {
    await mount(true)
    await act(async () => {
      await vi.waitFor(() => expect(dialog().textContent).toContain('Conversation A'))
    })
    act(() => (dialog().querySelector('input[type="checkbox"]') as HTMLInputElement).click())
    act(() => button('下一步').click())
    start()
    await act(async () => {
      await vi.waitFor(() => expect(controlled.api.evaluationApi.generateFromConversations).toHaveBeenCalled())
    })
    expect(controlled.api.evaluationApi.generateFromConversations).toHaveBeenCalledExactlyOnceWith({
      conversation_ids: [CONVERSATION_A],
      num_questions: 10,
      quality_threshold: 0.7,
      auto_save_as_cases: true,
    })
    expect(dialog().textContent).toContain('Conversation generated question')
  })

  it('preserves current API failure feedback and releases the generation control', async () => {
    controlled.api.evaluationApi.generateFromDocuments.mockResolvedValue({
      status: 'failed',
      generated_questions: [],
      saved_case_ids: [],
      error_message: 'Current generation failed',
    } satisfies TestGenResponse)
    await mount()
    start()
    await act(async () => {
      await vi.waitFor(() => expect(controlled.toast.error).toHaveBeenCalledWith('生成失败'))
    })
    expect(dialog().textContent).toContain('Current generation failed')
    expect(generationButton().disabled).toBe(false)
    expect(controlled.api.evaluationApi.listRegressionCases).toHaveBeenCalledOnce()
  })
})
