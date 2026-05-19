import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('observability section source', () => {
  it('uses business-facing Chinese labels instead of exposing raw field names in titles', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'observability-section.tsx'), 'utf8')

    expect(src).toContain('工具调用记录')
    expect(src).toContain('工作流运行记录')
    expect(src).toContain('RAG 过程指标')
    expect(src).toContain('配置键：tool_call_log')
    expect(src).toContain('配置键：agent_log')
    expect(src).toContain('配置键：metrics_log')
    expect(src).toContain('日志文件：logs/rag_metrics.jsonl')
    expect(src).toContain('保存后对新请求生效')
    expect(src).not.toContain('工具调用日志（tool_call_log）')
    expect(src).not.toContain('工作流生命周期日志（agent_log）')
    expect(src).not.toContain('RAG 指标日志（metrics_log，JSONL）')
  })
})
