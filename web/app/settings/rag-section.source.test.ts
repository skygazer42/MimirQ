import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('settings RAG section', () => {
  it('persists reranker defaults through real settings fields', () => {
    const section = read('./_sections/rag-section.tsx')

    expect(section).toContain("import { RERANKER_PROVIDER_OPTIONS } from '@/lib/reranker-provider-options'")
    expect(section).toContain('value={rag.reranker_provider ||')
    expect(section).toContain('onValueChange={(value) => updateRag({ reranker_provider: value })}')
    expect(section).toContain('RERANKER_PROVIDER_OPTIONS.map')
    expect(section).toContain('<SelectValue placeholder="选择重排服务" />')
    expect(section).toContain('value={rag.reranker_top_n}')
    expect(section).toContain('reranker_top_n: Math.max(')
    expect(section).toContain('RERANKER_PROVIDER')
    expect(section).toContain('RERANKER_TOP_N')
    expect(section).not.toContain('需要先在“重排序模型”里配置 Provider')
  })
})
