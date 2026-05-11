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
})
