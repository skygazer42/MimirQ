'use client'

import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { datasetApi, pipelineApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { randomBase36Id } from '@/lib/secure-random'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES } from '@/lib/chunk-strategies'
import type { IngestionPolicy, IngestionPreviewResponse, IngestionRule } from '@/types'
import { insertTemplate, newRuleDraft, policyPayload, ruleToDraft, type RuleDraft, type TemplatePlacement } from './policy-model'
import type { IngestionPolicyTemplate } from './policy-catalog'

const PROFILE_PARAMS = { include_builtin: true, limit: 200 } as const
export function useIngestionPolicy(datasetId: string) {
  const client = useQueryClient(), capabilities = usePipelineCapabilities(), lock = useRef(false)
  const datasetQuery = useQuery({ queryKey: queryKeys.datasets.detail(datasetId), queryFn: () => datasetApi.get(datasetId), retry: false })
  const policyQuery = useQuery({ queryKey: queryKeys.datasets.ingestionPolicy(datasetId), queryFn: async () => policyPayload(await datasetApi.getIngestionPolicy(datasetId)), retry: false, refetchOnWindowFocus: false })
  const statsQuery = useQuery({ queryKey: queryKeys.datasets.ingestionStats(datasetId), queryFn: () => datasetApi.getIngestionStats(datasetId), retry: false })
  const profilesQuery = useQuery({ queryKey: queryKeys.governance.profiles(PROFILE_PARAMS), queryFn: () => pipelineApi.listGovernanceProfiles(PROFILE_PARAMS), retry: false })
  const [local, setLocal] = useState<IngestionPolicy | null>(null), [saving, setSaving] = useState(false), [saveError, setSaveError] = useState('')
  const [editor, setEditor] = useState<{ originalId: string | null; draft: RuleDraft } | null>(null), [templatesOpen, setTemplatesOpen] = useState(false), [previewOpen, setPreviewOpen] = useState(false), [overviewOpen, setOverviewOpen] = useState(false)
  const [previewFile, setPreviewFile] = useState<File | null>(null), [preview, setPreview] = useState<IngestionPreviewResponse | null>(null), [previewing, setPreviewing] = useState(false), [previewError, setPreviewError] = useState('')
  const [discardOpen, setDiscardOpen] = useState(false)
  const focusTarget = useRef<HTMLElement | null>(null)
  const policy = local ?? policyQuery.data, rules = policy?.rules ?? []
  const dirty = local !== null && JSON.stringify(local) !== JSON.stringify(policyQuery.data)
  const blocked = saving || previewing || !policy || policyQuery.isError || datasetQuery.isError
  const chunkOptions = capabilities.capabilities?.chunk_strategies?.length ? capabilities.capabilities.chunk_strategies.map(item => item.name) : INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES

  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  function changeRules(next: IngestionRule[]) {
    if (!policy || lock.current) return
    setLocal({ version: policy.version, rules: next }); setSaveError(''); setPreview(null); setPreviewError('')
  }
  function openEditor(rule: IngestionRule | null, trigger: HTMLElement) {
    focusTarget.current = trigger
    setEditor({ originalId: rule?.id ?? null, draft: rule ? ruleToDraft(rule) : newRuleDraft(`rule-${randomBase36Id(10)}`) })
  }
  function applyRule(rule: IngestionRule, originalId: string | null) {
    const next = originalId === null ? insertTemplate(rules, [rule], 'prepend') : rules.map(item => item.id === originalId ? rule : item)
    changeRules(next); setEditor(null)
  }
  function removeRule(id: string) { changeRules(rules.filter(rule => rule.id !== id)) }
  function moveRule(id: string, direction: -1 | 1) {
    const index = rules.findIndex(rule => rule.id === id), target = index + direction
    if (index < 0 || target < 0 || target >= rules.length) return
    const next = [...rules]; [next[index], next[target]] = [next[target], next[index]]; changeRules(next)
  }
  function applyTemplate(template: IngestionPolicyTemplate, placement: TemplatePlacement) {
    const key = randomBase36Id(10), additions = template.rules.map((rule, index) => ({ ...rule, id: `tpl-${key}-${index + 1}` }))
    changeRules(insertTemplate(rules, additions, placement)); setTemplatesOpen(false)
  }
  async function save() {
    if (!policy || lock.current || !dirty) return
    lock.current = true; setSaving(true); setSaveError('')
    try {
      await client.cancelQueries({ queryKey: queryKeys.datasets.ingestionPolicy(datasetId) })
      const response = policyPayload(await datasetApi.updateIngestionPolicy(datasetId, policyPayload(policy)))
      client.setQueryData(queryKeys.datasets.ingestionPolicy(datasetId), response); setLocal(null); setPreview(null)
      toast.success(`${datasetQuery.data?.name ?? '数据集'}的入库策略已保存`)
      // Keep a later refresh failure separate from the successful PUT.
      await client.invalidateQueries({ queryKey: queryKeys.datasets.ingestionPolicy(datasetId) })
    } catch (error) { setSaveError(formatApiError(error, '保存策略失败')) }
    finally { lock.current = false; setSaving(false) }
  }
  async function runPreview() {
    if (!previewFile || dirty || blocked || lock.current) return
    lock.current = true; setPreviewing(true); setPreviewError(''); setPreview(null)
    try { setPreview(await pipelineApi.ingestionPreview(previewFile, { dataset_id: datasetId, diff_max_lines: 2000 })) }
    catch (error) { setPreviewError(formatApiError(error, '文件预览失败')) }
    finally { lock.current = false; setPreviewing(false) }
  }
  function restoreFocus() {
    if (focusTarget.current?.isConnected) focusTarget.current.focus()
    else document.querySelector<HTMLElement>('[data-policy-add]')?.focus()
  }
  function discard() { setLocal(null); setSaveError(''); setDiscardOpen(false); setPreview(null) }
  return {
    datasetId, datasetQuery, policyQuery, statsQuery, profilesQuery, capabilities, chunkOptions, policy, rules, dirty, blocked, saving, saveError, save, changeRules, removeRule, moveRule, editor, setEditor, openEditor, applyRule,
    templatesOpen, setTemplatesOpen, applyTemplate, previewOpen, setPreviewOpen, overviewOpen, setOverviewOpen, previewFile, preview, previewing, previewError, runPreview,
    setPreviewFile: (file: File | null) => { setPreviewFile(file); setPreview(null); setPreviewError('') },
    captureFocus: (element: HTMLElement) => { focusTarget.current = element }, restoreFocus, discardOpen, setDiscardOpen, discard,
  }
}
export type IngestionPolicyController = ReturnType<typeof useIngestionPolicy>
