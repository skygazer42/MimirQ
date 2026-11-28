'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { datasetApi } from '@/lib/api/datasets'
import { pipelineApi } from '@/lib/api/pipeline'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionRevision } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { randomBase36Id } from '@/lib/secure-random'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES, isRetiredChunkStrategy } from '@/lib/chunk-strategies'
import type { IngestionPolicy, IngestionPreviewResponse, IngestionRule } from '@/types'
import {
  insertTemplate,
  newRuleDraft,
  policyPayload,
  ruleToDraft,
  type RuleDraft,
  type TemplatePlacement,
} from './policy-model'
import type { IngestionPolicyTemplate } from './policy-catalog'

const PROFILE_PARAMS = { include_builtin: true, limit: 200 } as const

export function useIngestionPolicy(datasetId: string) {
  const client = useQueryClient()
  const capabilities = usePipelineCapabilities()
  const activeRequest = useRef<object | null>(null)
  const mounted = useRef(false)
  const visit = useRef<object>({})
  const draftRevision = useRef(0)
  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId),
    queryFn: () => datasetApi.get(datasetId),
    retry: false,
  })
  const policyQuery = useQuery({
    queryKey: queryKeys.datasets.ingestionPolicy(datasetId),
    queryFn: async () => policyPayload(await datasetApi.getIngestionPolicy(datasetId)),
    retry: false,
    refetchOnWindowFocus: false,
  })
  const statsQuery = useQuery({
    queryKey: queryKeys.datasets.ingestionStats(datasetId),
    queryFn: () => datasetApi.getIngestionStats(datasetId),
    retry: false,
  })
  const profilesQuery = useQuery({
    queryKey: queryKeys.governance.profiles(PROFILE_PARAMS),
    queryFn: ({ signal }) => pipelineApi.listGovernanceProfiles(PROFILE_PARAMS, { signal }),
    retry: false,
  })
  const [draftPolicy, setDraftPolicy] = useState<IngestionPolicy | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [editor, setEditor] = useState<{ originalId: string | null; draft: RuleDraft } | null>(null)
  const [templatesOpen, setTemplatesOpen] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [overviewOpen, setOverviewOpen] = useState(false)
  const [previewFile, setPreviewFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<IngestionPreviewResponse | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [previewError, setPreviewError] = useState('')
  const [discardOpen, setDiscardOpen] = useState(false)
  const focusTarget = useRef<HTMLElement | null>(null)
  const policy = draftPolicy ?? policyQuery.data
  const rules = policy?.rules ?? []
  const dirty = draftPolicy !== null && JSON.stringify(draftPolicy) !== JSON.stringify(policyQuery.data)
  const blocked = saving || previewing || !policy || policyQuery.isError || datasetQuery.isError
  const chunkOptions = capabilities.capabilities?.chunk_strategies?.length
    ? capabilities.capabilities.chunk_strategies
        .map((item) => item.name)
        .filter((name) => !isRetiredChunkStrategy(name))
    : INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])
  useLayoutEffect(() => {
    visit.current = {}
    activeRequest.current = null
    draftRevision.current += 1
    setDraftPolicy(null)
    setSaving(false)
    setSaveError('')
    setEditor(null)
    setPreview(null)
    setPreviewFile(null)
    setPreviewing(false)
    setPreviewError('')
    return () => {
      visit.current = {}
    }
  }, [datasetId])

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  function changeRules(next: IngestionRule[]) {
    if (policy === undefined || activeRequest.current !== null) return
    draftRevision.current += 1
    setDraftPolicy({ version: policy.version, rules: next })
    setSaveError('')
    setPreview(null)
    setPreviewError('')
  }
  function openEditor(rule: IngestionRule | null, trigger: HTMLElement) {
    focusTarget.current = trigger
    setEditor({
      originalId: rule?.id ?? null,
      draft: rule ? ruleToDraft(rule) : newRuleDraft(`rule-${randomBase36Id(10)}`),
    })
  }
  function applyRule(rule: IngestionRule, originalId: string | null) {
    const next =
      originalId === null
        ? insertTemplate(rules, [rule], 'prepend')
        : rules.map((item) => (item.id === originalId ? rule : item))
    changeRules(next)
    setEditor(null)
  }
  function removeRule(id: string) {
    changeRules(rules.filter((rule) => rule.id !== id))
  }
  function moveRule(id: string, direction: -1 | 1) {
    const index = rules.findIndex((rule) => rule.id === id)
    const target = index + direction
    if (index < 0 || target < 0 || target >= rules.length) return
    const next = [...rules]
    ;[next[index], next[target]] = [next[target], next[index]]
    changeRules(next)
  }
  function applyTemplate(template: IngestionPolicyTemplate, placement: TemplatePlacement) {
    const key = randomBase36Id(10)
    const additions = template.rules.map((rule, index) => ({ ...rule, id: `tpl-${key}-${index + 1}` }))
    changeRules(insertTemplate(rules, additions, placement))
    setTemplatesOpen(false)
  }
  async function save() {
    if (blocked || activeRequest.current !== null || !dirty) return
    const submission = {}
    const owner = visit.current
    const revision = draftRevision.current
    const sessionRevision = getAuthSessionRevision()
    const queryKey = queryKeys.datasets.ingestionPolicy(datasetId)
    const ownsView = () => mounted.current && visit.current === owner && sessionRevision === getAuthSessionRevision()
    activeRequest.current = submission
    setSaving(true)
    setSaveError('')
    try {
      await client.cancelQueries({ queryKey, exact: true })
      if (sessionRevision !== getAuthSessionRevision()) return
      const previousPolicy = client.getQueryData(queryKey)
      const response = policyPayload(await datasetApi.updateIngestionPolicy(datasetId, policyPayload(policy)))
      if (sessionRevision !== getAuthSessionRevision()) return
      if (ownsView() || client.getQueryData(queryKey) === previousPolicy) {
        client.setQueryData(queryKey, response)
      } else {
        void client.invalidateQueries({ queryKey, exact: true })
      }
      if (!ownsView() || draftRevision.current !== revision) return
      setDraftPolicy(null)
      setPreview(null)
      toast.success(`${datasetQuery.data?.name ?? '数据集'}的入库策略已保存`)
    } catch (error) {
      if (ownsView()) setSaveError(formatApiError(error, '保存策略失败'))
    } finally {
      if (activeRequest.current === submission) {
        activeRequest.current = null
        if (mounted.current) setSaving(false)
      }
    }
  }
  async function runPreview() {
    if (previewFile === null || dirty || blocked || activeRequest.current !== null) return
    const submission = {}
    const owner = visit.current
    const revision = draftRevision.current
    const sessionRevision = getAuthSessionRevision()
    const ownsView = () =>
      mounted.current &&
      visit.current === owner &&
      draftRevision.current === revision &&
      sessionRevision === getAuthSessionRevision()
    activeRequest.current = submission
    setPreviewing(true)
    setPreviewError('')
    setPreview(null)
    try {
      const response = await pipelineApi.ingestionPreview(previewFile, { dataset_id: datasetId, diff_max_lines: 2000 })
      if (ownsView()) setPreview(response)
    } catch (error) {
      if (ownsView()) setPreviewError(formatApiError(error, '文件预览失败'))
    } finally {
      if (activeRequest.current === submission) {
        activeRequest.current = null
        if (mounted.current) setPreviewing(false)
      }
    }
  }
  function restoreFocus() {
    if (focusTarget.current?.isConnected) focusTarget.current.focus()
    else document.querySelector<HTMLElement>('[data-policy-add]')?.focus()
  }
  function discard() {
    draftRevision.current += 1
    setDraftPolicy(null)
    setSaveError('')
    setDiscardOpen(false)
    setPreview(null)
  }
  return {
    datasetId,
    datasetQuery,
    policyQuery,
    statsQuery,
    profilesQuery,
    capabilities,
    chunkOptions,
    policy,
    rules,
    dirty,
    blocked,
    saving,
    saveError,
    save,
    changeRules,
    removeRule,
    moveRule,
    editor,
    setEditor,
    openEditor,
    applyRule,
    templatesOpen,
    setTemplatesOpen,
    applyTemplate,
    previewOpen,
    setPreviewOpen,
    overviewOpen,
    setOverviewOpen,
    previewFile,
    preview,
    previewing,
    previewError,
    runPreview,
    setPreviewFile: (file: File | null) => {
      draftRevision.current += 1
      setPreviewFile(file)
      setPreview(null)
      setPreviewError('')
    },
    captureFocus: (element: HTMLElement) => {
      focusTarget.current = element
    },
    restoreFocus,
    discardOpen,
    setDiscardOpen,
    discard,
  }
}
export type IngestionPolicyController = ReturnType<typeof useIngestionPolicy>
