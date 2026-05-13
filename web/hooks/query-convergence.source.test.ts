import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('query convergence source', () => {
  it('uses query keys and useQuery for pipeline capabilities', () => {
    const src = read('../contexts/pipeline-capabilities-context.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.pipeline.capabilities')
    expect(src).toContain("import { normalizeParserBackendName } from '@/lib/parser-compat'")
    expect(src).not.toContain('function normalizeParserBackendName')
  })

  it('uses useQuery for auth profile loading', () => {
    const src = read('./use-auth.ts')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.auth.profile')
  })

  it('uses useQuery for connector runs loading', () => {
    const src = read('./use-connector-runs.ts')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.connectors.runs')
  })

  it('uses useQuery for shared dataset list loading', () => {
    const src = read('./use-datasets.ts')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.datasets.list')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setDatasets(')
  })

  it('uses the shared dataset query hook for dataset select controls', () => {
    const src = read('../components/ops/dataset-select-field.tsx')

    expect(src).toContain("from '@/hooks/use-datasets'")
    expect(src).toContain('useDatasets()')
    expect(src).not.toContain('datasetApi.list')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setDatasets(')
  })

  it('uses useQuery for reusable group selection controls', () => {
    const src = read('../components/groups/group-chips-input.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKeys.groups.list')
    expect(src).not.toContain('groupApi.listGroups({ limit: 1000 })')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setGroups(')
    expect(src).not.toContain('setLoading(')
  })

  it('uses query-backed loading and mutations for the settings groups page', () => {
    const src = read('../app/settings/groups/page.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKeys.groups.list')
    expect(src).toContain('queryClient.invalidateQueries')
    expect(src).not.toContain('didRequestInitialLoadRef')
    expect(src).not.toContain('setGroups(')
    expect(src).not.toContain('setLoading(')
    expect(src).not.toContain('detachPromise(refresh())')
    expect(src).not.toContain('await refresh()')
  })

  it('uses query-backed loading and mutations for the settings group detail page', () => {
    const src = read('../app/settings/groups/[id]/page.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKeys.groups.detail')
    expect(src).toContain('queryKeys.groups.members')
    expect(src).toContain('queryClient.invalidateQueries')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setGroup(')
    expect(src).not.toContain('setMembers(')
    expect(src).not.toContain('setLoadingGroup(')
    expect(src).not.toContain('setLoadingMembers(')
    expect(src).not.toContain('detachPromise(loadGroup())')
    expect(src).not.toContain('detachPromise(loadMembers())')
  })

  it('uses query-backed loading and mutations for the settings RBAC page', () => {
    const src = read('../app/settings/rbac/page.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKeys.rbac.members')
    expect(src).toContain('queryClient.setQueryData')
    expect(src).toContain('queryClient.invalidateQueries')
    expect(src).not.toContain('detachPromise(refresh())')
    expect(src).not.toContain('setMembers(')
    expect(src).not.toContain('setLoading(')
  })

  it('uses query-backed summary loading and export mutation for access review', () => {
    const src = read('../app/access-review/page.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKeys.accessReview.summary')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setSummary(')
    expect(src).not.toContain('setLoadingSummary(')
    expect(src).not.toContain('setExporting(')
    expect(src).not.toContain('detachPromise(loadSummary())')
    expect(src).not.toContain('detachPromise(handleDownload())')
  })

  it('uses useQuery for index audit results', () => {
    const src = read('./use-index-audit.ts')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.indexAudit.result')
  })

  it('uses useQuery for audit log page loading and filter options', () => {
    const src = read('../app/audit/page.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.audit.logs')
    expect(src).toContain('queryKey: queryKeys.audit.filterOptions')
    expect(src).not.toContain('detachPromise(load())')
    expect(src).not.toContain('setResp(')
    expect(src).not.toContain('setFilterSeedItems(')
  })

  it('uses useQuery for usage summary, cost, quota, and dataset labels', () => {
    const src = read('../app/usage/page.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.usage.summary')
    expect(src).toContain('queryKey: queryKeys.usage.cost')
    expect(src).toContain('queryKey: queryKeys.usage.quota')
    expect(src).toContain('queryKey: queryKeys.datasets.list')
    expect(src).not.toContain('detachPromise(load(')
    expect(src).not.toContain('setSummary(')
    expect(src).not.toContain('setCost(')
    expect(src).not.toContain('setQuota(')
    expect(src).not.toContain('setDatasetNameById(')
  })

  it('uses useQuery and query invalidation for prompt template lists', () => {
    const src = read('../app/prompts/page.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('useQueryClient(')
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.prompts.list')
    expect(src).toContain('queryClient.invalidateQueries')
    expect(src).toContain('queryKey: queryKeys.prompts.all')
    expect(src).not.toContain('setTemplates(')
    expect(src).not.toContain('setLoading(')
    expect(src).not.toContain('loadTemplates()')
  })

  it('uses useQuery for reports datasets, categories, and previews', () => {
    const src = read('../app/reports/page-client.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.datasets.list')
    expect(src).toContain('queryKey: queryKeys.reports.categories')
    expect(src).toContain('queryKey: queryKeys.reports.dataset')
    expect(src).not.toContain('setDatasets(')
    expect(src).not.toContain('setReport(r)')
    expect(src).not.toContain('setReport(null)')
    expect(src).not.toContain('setCategoryTree(')
    expect(src).not.toContain('detachPromise(loadDatasets())')
    expect(src).not.toContain('detachPromise(loadCategories())')
    expect(src).not.toContain('detachPromise(loadReport())')
  })

  it('uses useQuery for diagnostics backend snapshots and selectors', () => {
    const src = read('../app/diagnostics/page-client.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.datasets.list')
    expect(src).toContain('queryKey: queryKeys.documents.list')
    expect(src).toContain('queryKey: queryKeys.diagnostics.onlineQuality')
    expect(src).toContain('queryKey: queryKeys.diagnostics.ready')
    expect(src).toContain('queryKey: queryKeys.diagnostics.deps')
    expect(src).not.toContain('setDatasets(')
    expect(src).not.toContain('setDocuments(')
    expect(src).not.toContain('setOnlineQuality(')
    expect(src).not.toContain('setReadySnapshot(')
    expect(src).not.toContain('setDepsSnapshot(')
    expect(src).not.toContain('refreshDatasets')
    expect(src).not.toContain('refreshDocuments')
    expect(src).not.toContain('refreshOnlineQuality')
    expect(src).not.toContain('refreshReadySnapshot')
    expect(src).not.toContain('refreshDepsSnapshot')
  })

  it('uses query-backed dataset loading for KG search diagnostics', () => {
    const src = read('../components/graph/kg-diagnostics-page.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.datasets.list')
    expect(src).not.toContain('setDatasets(')
    expect(src).not.toContain('setDatasetsLoading(')
    expect(src).not.toContain('datasetApi.list({ limit: 200 })')
  })

  it('uses query-backed loading and mutation for KG extract prompt settings', () => {
    const src = read('../components/kg-extract-prompt-settings.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.settings.snapshot')
    expect(src).toContain('queryClient.invalidateQueries')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setLoading(')
    expect(src).not.toContain('setSaving(')
    expect(src).not.toContain('setOriginal(')
    expect(src).not.toContain('settingsApi.get()')
  })

  it('uses query-backed settings status loading for parser health badges', () => {
    const src = read('../components/business/parser-dropdown.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.settings.status')
    expect(src).toContain('queryFn: settingsApi.getStatus')
    expect(src).not.toContain('setPaddleVlVersionBadge')
    expect(src).not.toContain('loadPaddleVlHealth')
    expect(src).not.toContain('let cancelled = false')
  })

  it('uses query-backed loading and mutations for KG predicate ontology settings', () => {
    const src = read('../components/kg-predicate-ontology-settings.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.settings.snapshot')
    expect(src).toContain('queryKey: queryKeys.kg.predicateOntology')
    expect(src).toContain('queryClient.invalidateQueries')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setLoading(')
    expect(src).not.toContain('setSaving(')
    expect(src).not.toContain('setRows(')
    expect(src).not.toContain('setKgEnabled(')
    expect(src).not.toContain('settingsApi.get()')
    expect(src).not.toContain('load()')
  })

  it('uses useQuery for data cleaner prompt template loading', () => {
    const src = read('../components/data-governance/data-cleaner.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.prompts.list')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setPromptTemplates(')
    expect(src).not.toContain('loadTemplates')
  })

  it('uses useQuery for governance profile selector loading', () => {
    const src = read('../components/governance-profile-selector.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.governance.profiles')
    expect(src).toContain('queryKey: queryKeys.governance.profileResolved')
    expect(src).toContain('queryClient.invalidateQueries')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('setLoading(')
    expect(src).not.toContain('setProfiles(')
    expect(src).not.toContain('setSelectedResolved(')
    expect(src).not.toContain('loadProfiles')
  })

  it('uses useQuery for settings industry rules ruleset loading', () => {
    const src = read('../app/settings/_sections/industry-rules-section.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.industryRules.rulesets')
    expect(src).not.toContain('useEffect(')
    expect(src).not.toContain('didLoadRulesetsRef')
    expect(src).not.toContain('setRulesets(')
  })

  it('uses query-backed loading and mutations for Golden regression cases', () => {
    const src = read('../components/test-case-manager.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.evaluations.regressionCases')
    expect(src).toContain('queryClient.invalidateQueries')
    expect(src).not.toContain('setCases(')
    expect(src).not.toContain('setIsLoading(')
    expect(src).not.toContain('loadCases')
  })

  it('uses query-backed dataset loading for regression evaluation scope', () => {
    const src = read('../components/evaluation/regression-tab.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.datasets.list')
    expect(src).not.toContain('setDatasets(')
    expect(src).not.toContain('setIsLoadingDatasets(')
    expect(src).not.toContain('datasetApi.list({ limit: 200 })')
  })

  it('uses useQuery for dataset folder tree loading', () => {
    const src = read('../components/document-library/dataset-folder-tree.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.documents.folders')
    expect(src).not.toContain('setTree(')
    expect(src).not.toContain('setLoading(')
    expect(src).not.toContain('detachPromise(load())')
  })

  it('uses query-backed loading for lineage dialogs', () => {
    const answerSrc = read('../components/history/answer-lineage-action.tsx')
    const chunkSrc = read(
      '../components/document-detail-dialog/document-detail-activity-panel.tsx'
    )

    expect(answerSrc).toContain("from '@tanstack/react-query'")
    expect(answerSrc).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(answerSrc).toContain('queryKey: queryKeys.lineage.answer')
    expect(answerSrc).not.toContain('setLoading(')
    expect(answerSrc).not.toContain('setPayload(')
    expect(answerSrc).not.toContain('detachPromise(loadLineage())')

    expect(chunkSrc).toContain("from '@tanstack/react-query'")
    expect(chunkSrc).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(chunkSrc).toContain('queryKey: queryKeys.lineage.chunk')
    expect(chunkSrc).not.toContain('setLoading(')
    expect(chunkSrc).not.toContain('setPayload(')
    expect(chunkSrc).not.toContain('detachPromise(loadLineage())')
  })

  it('uses query-backed loading and mutations for dataset category controls', () => {
    const treeSrc = read('../components/dataset-categories/category-tree.tsx')
    const multiSelectSrc = read(
      '../components/dataset-categories/category-multi-select.tsx'
    )

    expect(treeSrc).toContain("from '@tanstack/react-query'")
    expect(treeSrc).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(treeSrc).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(treeSrc).toContain('queryKey: queryKeys.datasetCategories.tree')
    expect(treeSrc).toContain('queryClient.invalidateQueries')
    expect(treeSrc).not.toContain('setResp(')
    expect(treeSrc).not.toContain('setLoading(')
    expect(treeSrc).not.toContain('detachPromise(load())')

    expect(multiSelectSrc).toContain("from '@tanstack/react-query'")
    expect(multiSelectSrc).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(multiSelectSrc).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(multiSelectSrc).toContain('queryKey: queryKeys.datasetCategories.tree')
    expect(multiSelectSrc).toContain('queryKey: queryKeys.datasets.categories')
    expect(multiSelectSrc).toContain('queryClient.setQueryData')
    expect(multiSelectSrc).not.toContain('setTree(')
    expect(multiSelectSrc).not.toContain('setAssigned(')
    expect(multiSelectSrc).not.toContain('setLoading(')
    expect(multiSelectSrc).not.toContain('detachPromise(load())')
  })

  it('uses QueryClient-backed loading for chat session messages', () => {
    const src = read('./use-chat-session.ts')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toContain('useQueryClient(')
    expect(src).toContain('queryKeys.chat.messages')
    expect(src).toContain('queryClient.fetchQuery')
  })

  it('uses useQuery and mutations for conversation summary memory', () => {
    const src = read('../components/chat/conversation-summary-dialog.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toMatch(/useMutation(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKeys.chat.summary')
    expect(src).toContain('queryClient.setQueryData')
    expect(src).not.toContain('React.useEffect(')
    expect(src).not.toContain('setLoading(')
    expect(src).not.toContain('setSummary(')
  })

  it('uses useQuery for knowledge settings panel loading', () => {
    const src = read('../components/knowledge/knowledge-settings-panel.tsx')

    expect(src).toContain("from '@tanstack/react-query'")
    expect(src).toMatch(/useQuery(?:<[\s\S]+?>)?\(\{/)
    expect(src).toContain('queryKey: queryKeys.settings.snapshot')
    expect(src).not.toContain('const loadSettings = useCallback(async () =>')
    expect(src).not.toContain('detachPromise(loadSettings())')
  })
})
