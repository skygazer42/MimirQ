import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ConversationOpsPanel source', () => {
  it('surfaces conversation creation, export and checkpoint APIs explicitly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'conversation-ops-panel.tsx'), 'utf8')

    for (const api of [
      'chatApi.createConversation',
      'chatApi.exportConversation',
      'chatApi.listCheckpoints',
      'chatApi.getCheckpoint',
      'chatApi.deleteCheckpoints',
    ]) {
      expect(src).toContain(api)
    }
  })

  it('keeps backend ids and raw json behind progressive disclosure', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'conversation-ops-panel.tsx'), 'utf8')

    expect(src).toContain('当前对话已自动绑定')
    expect(src).toContain('高级调试（可选）')
    expect(src).toContain('查看原始响应')
    expect(src).toContain('useState<{ title: string; payload: unknown } | null>(null)')
    expect(src).toContain('useState(false)')
    expect(src).toContain('{result ? (')
    expect(src).not.toContain('等待创建对话、导出或检查 checkpoint')
    expect(src).not.toContain('<Field label="conversation_id">')
    expect(src).not.toContain('<Field label="checkpoint_id">')
    expect(src).not.toContain('<Field label="document_ids">')
  })
})
