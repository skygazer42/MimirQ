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
      'chatApi.deleteCheckpoints',
    ]) {
      expect(src).toContain(api)
    }

    expect(src).not.toContain('chatApi.getCheckpoint')
  })

  it('keeps backend ids and raw json behind progressive disclosure', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'conversation-ops-panel.tsx'), 'utf8')

    expect(src).toContain('当前对话自动绑定')
    expect(src).toContain('const [panelOpen, setPanelOpen] = useState(false)')
    expect(src).toContain('aria-expanded={panelOpen}')
    expect(src).toContain("{panelOpen ? (")
    expect(src).toContain("panelOpen ? '收起面板' : '展开操作'")
    expect(src).toContain('对话运维工具箱')
    expect(src).toContain('导出 · 检查点')
    expect(src).toContain('已收起，展开后可导出对话、查看检查点或清理缓存。')
    expect(src).toContain("{hasConversation ? '已绑定' : '未选择'}")
    expect(src).toContain('检查点列表')
    expect(src).toContain('查看原始响应')
    expect(src).toContain('useState<{ title: string; payload: unknown } | null>(null)')
    expect(src).toContain('useState(false)')
    expect(src).toContain('{result ? (')
    expect(src).not.toContain('等待创建对话、导出或检查 checkpoint')
    expect(src).not.toContain('点击展开导出、查看 checkpoint 或清理缓存')
    expect(src).not.toContain('低频工具')
    expect(src).not.toContain('<Field label="conversation_id">')
    expect(src).not.toContain('<Field label="checkpoint_id">')
    expect(src).not.toContain('<Field label="document_ids">')
    expect(src).not.toContain('高级调试（可选）')
    expect(src).not.toContain('checkpointId')
    expect(src).not.toContain('Checkpoint 编号')
    expect(src).not.toContain('Checkpoint 详情')
    expect(src).not.toContain('include_values: true')
  })
})
