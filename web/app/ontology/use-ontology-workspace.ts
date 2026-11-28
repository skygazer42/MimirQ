'use client'

import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { enterpriseOntologyApi } from '@/lib/api/enterprise-ontology'
import { datasetApi } from '@/lib/api/datasets'
import type {
  EnterpriseOntologyDefinitionView as Definition,
  EnterpriseOntologyWorkspaceView as Workspace,
  EnterpriseOntologySuggestionView as Suggestion,
  EnterpriseOntologyBindingPreviewView as BindingPreview,
  EnterpriseOntologyExtractionPreviewView as ExtractionPreview,
  EnterpriseOntologyPreviewInput,
  EnterpriseOntologyRuleCandidate as RuleCandidate,
} from '@/types/enterprise-ontology'
import { assetObjectId, emptyDefinition, getAssets, ontologyErrorText, type AssetCategory } from './ontology-model'

export function useOntologyWorkspace(sessionKey: string) {
  const client = useQueryClient()
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [definition, setDefinition] = useState<Definition>(emptyDefinition)
  const [started, setStarted] = useState(false)
  const [stage, setStage] = useState('model')
  const [visitedRuntime, setVisitedRuntime] = useState(false)
  const [category, setCategory] = useState<AssetCategory>('object_types')
  const [objectTab, setObjectTab] = useState('properties')
  const [selectedAsset, setSelectedAsset] = useState('')
  const [selected, setSelected] = useState('')
  const [versionId, setVersionId] = useState('')
  const [importOpen, setImportOpen] = useState(false)
  const [assetDatasetId, setAssetDatasetId] = useState('')
  const [suggestionAssets, setSuggestionAssets] = useState<string[]>([])
  const [suggestionSample, setSuggestionSample] = useState('')
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null)
  const [definitionText, setDefinitionText] = useState<string | null>(null)
  const [importText, setImportText] = useState('')
  const [sample, setSample] = useState('')
  const [documentId, setDocumentId] = useState('')
  const [bindingResults, setBindingResults] = useState<BindingPreview[]>([])
  const [extraction, setExtraction] = useState<ExtractionPreview[]>([])
  const [ruleCandidates, setRuleCandidates] = useState<RuleCandidate[] | null>(null)
  const [busy, setBusy] = useState('')
  const [issue, setIssue] = useState('')
  const [notice, setNotice] = useState('')
  const [edoCredential, setEdoCredential] = useState('')
  const workspaceKey = ['enterprise-ontology', 'workspaces', sessionKey]
  const workspaces = useQuery({
    queryKey: workspaceKey,
    queryFn: ({ signal }) => enterpriseOntologyApi.listWorkspaces({ signal }),
    retry: false,
  })
  const versions = useQuery({
    queryKey: ['enterprise-ontology', 'versions', sessionKey, workspace?.id],
    queryFn: ({ signal }) => enterpriseOntologyApi.listVersions(workspace!.id, { signal }),
    enabled: Boolean(workspace),
    retry: false,
  })
  const publishedVersion = versions.data?.find((item) => item.id === (versionId || versions.data[0]?.id))
  const hasEdo =
    definition.bindings.some((binding) => binding.edo_binding) ||
    Boolean(publishedVersion?.definition.bindings.some((binding) => binding.edo_binding))
  const edoHeaders = hasEdo && edoCredential.trim() ? { 'X-EDO-Authorization': edoCredential.trim() } : undefined
  const browseAssets =
    importOpen ||
    (stage === 'model' && (category === 'bindings' || (category === 'object_types' && objectTab === 'bindings')))
  const datasets = useQuery({
    queryKey: ['enterprise-ontology', 'datasets', sessionKey],
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
    enabled: browseAssets,
    retry: false,
  })
  const assets = useQuery({
    queryKey: ['enterprise-ontology', 'assets', sessionKey, assetDatasetId],
    queryFn: ({ signal }) => enterpriseOntologyApi.listAssets({ dataset_id: assetDatasetId }, { signal }),
    enabled: browseAssets && Boolean(assetDatasetId),
    retry: false,
  })

  useEffect(() => {
    if (started || !workspaces.isSuccess || !workspaces.data.length) return
    const record = workspaces.data[0]
    setWorkspace(record)
    setDefinition(record.draft)
    setSelected(Object.keys(record.draft.object_types)[0] ?? '')
    setStarted(true)
  }, [started, workspaces.data, workspaces.isSuccess])

  function mutate(next: Definition) {
    setDefinition(next)
    setBindingResults([])
    setExtraction([])
    setRuleCandidates(null)
    setSuggestion(null)
    setNotice('')
  }
  function changeStage(value: string) {
    setStage(value)
    if (value === 'runtime') setVisitedRuntime(true)
  }
  function chooseAsset(value: AssetCategory, id = '') {
    const assetId = id || (value === 'object_types' ? selected : (getAssets(definition, value)[0]?.id ?? ''))
    setCategory(value)
    setSelectedAsset(assetId)
    const objectId = assetId ? assetObjectId(definition, value, assetId) : undefined
    if (objectId) setSelected(objectId)
    changeStage('model')
  }
  function openWorkspace(id: string) {
    const record = workspaces.data?.find((item) => item.id === id) ?? null
    setStarted(true)
    setWorkspace(record)
    mutate(record?.draft ?? emptyDefinition())
    setSelected(Object.keys(record?.draft.object_types ?? {})[0] ?? '')
    setSelectedAsset('')
    setVersionId('')
    setDefinitionText(null)
    setImportText('')
    setSuggestionSample('')
    setSuggestionAssets([])
    setIssue('')
  }
  async function run(action: string, task: () => Promise<void>) {
    setBusy(action)
    setIssue('')
    setNotice('')
    try {
      await task()
    } catch (error) {
      setIssue(ontologyErrorText(error))
    } finally {
      setBusy('')
    }
  }
  async function save() {
    await run('保存草稿', async () => {
      const updated = workspace
        ? await enterpriseOntologyApi.updateDraft(workspace.id, {
            definition,
            expected_revision: workspace.draft_revision,
          })
        : await enterpriseOntologyApi.createWorkspace(definition)
      setWorkspace(updated)
      setDefinition(updated.draft)
      client.setQueryData<Workspace[]>(workspaceKey, (items = []) => [
        ...items.filter((item) => item.id !== updated.id),
        updated,
      ])
      setNotice('草稿已保存 · 修订 ' + updated.draft_revision)
    })
  }
  async function publish() {
    if (!workspace) return
    await run('发布版本', async () => {
      const data = await enterpriseOntologyApi.publishVersion(
        workspace.id,
        { expected_revision: workspace.draft_revision },
        { headers: edoHeaders },
      )
      await versions.refetch({ throwOnError: true })
      setVersionId(data.id)
      setNotice('已发布版本 ' + data.number)
    })
  }
  function loadDefinition(next: Definition) {
    setStarted(true)
    mutate(next)
    setSelected(Object.keys(next.object_types)[0] ?? '')
    setDefinitionText(null)
    setNotice('定义已应用到编辑区')
  }
  async function applyDefinition(content: string) {
    const data = await enterpriseOntologyApi.validateDefinition({
      content,
      format: content.trimStart().startsWith('{') ? 'json' : 'yaml',
    })
    if (workspace && data.ontology !== workspace.code) throw new Error('定义的本体标识与当前草稿不同')
    loadDefinition(data)
  }
  function previewBindings() {
    void run('检查绑定', async () =>
      setBindingResults(await enterpriseOntologyApi.previewBindings(definition, { headers: edoHeaders })),
    )
  }
  function previewSource(): EnterpriseOntologyPreviewInput['source'] {
    return documentId.trim() ? { kind: 'document', document_id: documentId.trim() } : { kind: 'sample', text: sample }
  }
  function clearExtraction() {
    setExtraction([])
    setRuleCandidates(null)
  }
  return {
    workspaces,
    workspace,
    definition,
    mutate,
    started,
    stage,
    changeStage,
    category,
    chooseAsset,
    objectTab,
    setObjectTab,
    selectedAsset,
    selected,
    setSelected,
    active: definition.object_types[selected],
    objectIds: Object.keys(definition.object_types),
    versions,
    publishedVersion,
    versionId: publishedVersion?.id ?? '',
    setVersionId,
    visitedRuntime,
    dirty: JSON.stringify(definition) !== JSON.stringify(workspace?.draft ?? emptyDefinition()),
    importOpen,
    setImportOpen,
    importText,
    setImportText,
    definitionText,
    setDefinitionText,
    unappliedDefinition: definitionText !== null,
    assetDatasetId,
    setAssetDatasetId,
    datasets,
    assets,
    suggestionAssets,
    setSuggestionAssets,
    suggestionSample,
    setSuggestionSample,
    suggestion,
    setSuggestion,
    generateSuggestion: () => {
      setSuggestion(null)
      void run('生成草案', async () =>
        setSuggestion(
          await enterpriseOntologyApi.suggestDefinition({
            ontology: definition.ontology,
            dataset_id: assetDatasetId,
            asset_ids: suggestionAssets,
            sample: suggestionSample.trim(),
          }),
        ),
      )
    },
    loadDefinition,
    applyDefinition,
    openWorkspace,
    save,
    publish,
    run,
    busy,
    issue,
    setIssue,
    notice,
    hasEdo,
    edoCredential,
    setEdoCredential,
    edoHeaders,
    bindingResults,
    previewBindings,
    extraction,
    ruleCandidates,
    documentId,
    setDocumentId: (value: string) => {
      setDocumentId(value)
      clearExtraction()
    },
    sample,
    setSample: (value: string) => {
      setSample(value)
      clearExtraction()
    },
    previewExtraction: () =>
      void run('抽取预检', async () =>
        setExtraction(await enterpriseOntologyApi.previewExtraction({ definition, source: previewSource() })),
      ),
    previewRules: () =>
      void run('提取规则候选', async () => {
        setRuleCandidates(null)
        setRuleCandidates(await enterpriseOntologyApi.previewRules({ definition, source: previewSource() }))
      }),
    addRule: (candidate: RuleCandidate) => {
      setDefinition({ ...definition, rules: { ...definition.rules, [candidate.id]: candidate.rule } })
      setNotice('规则已加入当前草稿。')
    },
  }
}
export type OntologyController = ReturnType<typeof useOntologyWorkspace>
