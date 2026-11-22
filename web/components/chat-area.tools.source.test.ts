// Source contract check only; interactive behavior is covered by browser verification.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chat composer tools source', () => {
  it('keeps dataset scope and retrieval settings in separate, mutually exclusive popups', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')
    const messages = fs.readFileSync(path.resolve(__dirname, '../i18n/messages/zh-CN/chat.ts'), 'utf8')

    expect(src).toMatch(/<DatasetScopePicker\s+open=\{datasetPickerOpen\}/)
    expect(src).toContain('if (open) setShowRagSettings(false)')
    expect(src).toContain('if (open) setDatasetPickerOpen(false)')
    expect(src).toContain('aria-controls="chat-retrieval-settings"')
    expect(src).toMatch(/<PopoverContent\s+id="chat-retrieval-settings"/)
    expect(messages).toContain("retrievalSettings: '检索设置'")
  })
})
