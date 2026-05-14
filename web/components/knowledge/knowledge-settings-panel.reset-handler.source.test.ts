import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel reset handler', () => {
  it('keeps reset changes inline beside the save action instead of using a separate dirty footer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('onClick={handleResetDraft}')
    expect(src).toMatch(/const handleResetDraft = useCallback\(/)
    expect(src).toContain('重置更改')
    expect(src).toContain('保存配置')
    expect(src).not.toContain('当前配置有未保存更改')
    expect(src).not.toContain('border-t border-sky-100/75 bg-white/80 px-3 py-2')
  })
})
