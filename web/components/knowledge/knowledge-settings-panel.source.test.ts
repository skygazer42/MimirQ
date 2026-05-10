import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel module', () => {
  it('exports KnowledgeSettingsPanel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('export function KnowledgeSettingsPanel')
  })

  it('normalizes connector run document ids before string conversion', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('getConnectorRunProgress')
    expect(src).toContain("Number(stats?.total_items || stats?.items_total || stats?.total_urls || 0)")
    expect(src).toContain("Number(stats?.processed_items || stats?.items_processed || stats?.processed_urls || 0)")
  })

  it('loads system settings into a controlled draft and saves them explicitly instead of relying on static defaults', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('settingsApi.get()')
    expect(src).toContain('settingsApi.update(draftConfig)')
    expect(src).toContain('const [savedConfig, setSavedConfig] = useState<KnowledgeSettingsConfig | null>(null)')
    expect(src).toContain('const [draftConfig, setDraftConfig] = useState<KnowledgeSettingsConfig | null>(null)')
    expect(src).toContain('const isDirty = useMemo(() => JSON.stringify(savedConfig) !== JSON.stringify(draftConfig)')
    expect(src).toContain('const handleResetDraft = useCallback(() => {')
    expect(src).toContain('const handleSave = async () => {')
    expect(src).toContain('const handleApplyRecommendedConfig = () => {')
    expect(src).toContain('保存当前配置')
    expect(src).not.toContain("toast.success('已保存为默认配置')")
    expect(src).not.toContain('配置备注（选填）')
    expect(src).not.toContain('2024-05-24 14:30')
    expect(src).not.toContain('admin')
  })
})
