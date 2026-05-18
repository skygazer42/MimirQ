import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeSettingsPanel module', () => {
  it('exports KnowledgeSettingsPanel', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-settings-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'export function KnowledgeSettingsPanel')
  })

  it('normalizes connector run document ids before string conversion', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-settings-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'getConnectorRunProgress')
    expectSourceToContain(
      src,
      'Number(stats?.total_items || stats?.items_total || stats?.total_urls || 0)'
    )
    expectSourceToContain(
      src,
      'Number(stats?.processed_items || stats?.items_processed || stats?.processed_urls || 0)'
    )
  })

  it('loads system settings into a controlled draft and saves them explicitly instead of relying on static defaults', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-settings-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'settingsApi.get()')
    expectSourceToContain(src, 'settingsApi.update(draftConfig)')
    expectSourceToContain(src, 'datasetApi.update(selectedDatasetId')
    expectSourceToContain(src, 'embedding_defaults: buildDatasetEmbeddingDefaults(draftConfig)')
    expectSourceToContain(
      src,
      'const [savedConfig, setSavedConfig] = useState<KnowledgeSettingsConfig | null>(null)'
    )
    expectSourceToContain(
      src,
      'const [draftConfig, setDraftConfig] = useState<KnowledgeSettingsConfig | null>(null)'
    )
    expectSourceToContain(
      src,
      'const isDirty = useMemo(() => JSON.stringify(savedConfig) !== JSON.stringify(draftConfig)'
    )
    expectSourceToContain(src, 'const handleResetDraft = useCallback(() => {')
    expectSourceToContain(src, 'const handleSave = async () => {')
    expectSourceToContain(src, 'const handleApplyRecommendedConfig = () => {')
    expectSourceToContain(src, '保存当前配置')
    expectSourceNotToContain(src, "toast.success('已保存为默认配置')")
    expectSourceNotToContain(src, '配置备注（选填）')
    expectSourceNotToContain(src, '2024-05-24 14:30')
    expectSourceNotToContain(src, 'admin')
  })

  it('binds qwen embedding presets as real provider plus api_base combinations', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-settings-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, "model: 'text-embedding-v4'")
    expectSourceToContain(src, "model: 'text-embedding-v3'")
    expectSourceToContain(src, "provider: 'dashscope'")
    expectSourceToContain(src, "apiBase: 'https://dashscope.aliyuncs.com/compatible-mode/v1'")
    expectSourceToContain(src, 'embedding: {')
    expectSourceToContain(src, 'provider: preset.provider')
    expectSourceToContain(src, 'api_base: preset.apiBase')
    expectSourceToContain(src, 'brand: \'Qwen Embedding\'')
  })

  it('makes the configuration guide trigger reveal inline guidance instead of being a dead button', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-settings-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'SETTINGS_GUIDE_PANEL_ID')
    expectSourceToContain(src, 'const [guideExpanded, setGuideExpanded] = useState(false)')
    expectSourceToContain(src, 'aria-expanded={guideExpanded}')
    expectSourceToContain(src, 'aria-controls={SETTINGS_GUIDE_PANEL_ID}')
    expectSourceToContain(src, 'onClick={() => setGuideExpanded((expanded) => !expanded)}')
    expectSourceToContain(src, "{guideExpanded ? '收起配置指南' : '查看配置指南'}")
    expectSourceToContain(src, '隔离文档不会因为配置变化自动重新嵌入')
  })

  it('scopes embedding settings to the selected dataset instead of mutating every dataset by default', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-settings-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'selectedDataset?: Dataset | null')
    expectSourceToContain(src, 'datasets?: Dataset[]')
    expectSourceToContain(src, 'onDatasetScopeChange?: (value: string) => void')
    expectSourceToContain(src, 'buildScopedSettingsConfig(settingsQuery.data, selectedDataset)')
    expectSourceToContain(src, 'selectedDataset?.embedding_defaults?.model')
    expectSourceToContain(src, '配置作用域')
    expectSourceToContain(src, 'value={selectedScopeValue}')
    expectSourceToContain(src, 'onValueChange={onDatasetScopeChange}')
    expectSourceToContain(src, '{scopeDatasetId}')
    expectSourceToContain(src, "toast.success('已保存到当前数据集，既有数据集不会被全局改动影响')")
    expectSourceToContain(src, '隔离中的文档保持隔离状态')
    expectSourceNotToContain(src, '所有文档必须重新进入 Ingestion')
  })

  it('uses the settings sidebar for dataset scope selection instead of a redundant section menu', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-settings-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(
      src,
      'const [currentConfigOpen, setCurrentConfigOpen] = useState(true)'
    )
    expectSourceToContain(src, '配置作用域')
    expectSourceToContain(src, '选择数据集')
    expectSourceToContain(src, '<SelectItem value={datasetAllValue}>')
    expectSourceToContain(src, 'aria-expanded={currentConfigOpen}')
    expectSourceToContain(
      src,
      'aria-controls="knowledge-current-config-panel"'
    )
    expectSourceToContain(
      src,
      'onClick={() => setCurrentConfigOpen((open) => !open)}'
    )
    expectSourceNotToContain(src, '配置来源')
    expectSourceNotToContain(src, '后端 /settings')
    expectSourceNotToContain(src, 'const navItems')
    expectSourceNotToContain(src, '嵌入模型配置</span>')
    expectSourceNotToContain(src, 'reranker 重排模型')
  })

  it('can hide the settings sidebar from the parent workbench collapse action', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-settings-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'settingsSidebarCollapsed?: boolean')
    expectSourceToContain(src, 'settingsSidebarCollapsed = false')
    expectSourceToContain(src, 'settingsSidebarCollapsed ?')
    expectSourceToContain(src, "'xl:grid-cols-1'")
    expectSourceToContain(src, "'xl:grid-cols-[206px_minmax(0,1fr)]'")
    expectSourceToContain(src, '{!settingsSidebarCollapsed ? (')
  })

  it('keeps the settings content scrollable after expanding the guide panel', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-settings-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'overflow-y-auto p-2 no-scrollbar xl:overflow-y-auto')
    expectSourceToContain(src, 'space-y-2.5 xl:h-full xl:max-h-full xl:min-h-0 xl:overflow-y-auto')
    expectSourceNotToContain(src, 'overflow-y-auto p-2 no-scrollbar xl:overflow-hidden')
  })
})
