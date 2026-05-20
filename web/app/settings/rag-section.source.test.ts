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
    expect(section).toContain("import { SettingsSwitch } from '@/components/settings/settings-switch'")
    expect(section).toContain('const rerankerProviderValue = rag.reranker_provider ||')
    expect(section).toContain('const rerankerProviderLabel = getRerankerProviderLabel(rerankerProviderValue)')
    expect(section).toContain('value={rerankerProviderValue}')
    expect(section).toContain('onValueChange={(value) => updateRag({ reranker_provider: value })}')
    expect(section).toContain('RERANKER_PROVIDER_OPTIONS.map')
    expect(section).toContain('<SelectValue placeholder="选择重排服务" />')
    expect(section).toContain('{rerankerProviderLabel}')
    expect(section).toContain('value={rag.reranker_top_n}')
    expect(section).toContain('reranker_top_n: Math.max(')
    expect(section).toContain('const showImageInAnswer = rag.show_image_in_answer')
    expect(section).toContain('checked={showImageInAnswer}')
    expect(section).toContain('updateRag({ show_image_in_answer: checked })')
    expect(section).toContain('value={rag.image_append_max}')
    expect(section).toContain('image_append_max: Math.max(')
    expect(section).toContain('回答附图')
    expect(section).toContain('最多附图')
    expect(section).toContain('RERANKER_PROVIDER')
    expect(section).toContain('RERANKER_TOP_N')
    expect(section).toContain('const RANGE_INPUT_CLASS')
    expect(section).toContain('[&::-webkit-slider-thumb]:bg-blue-600')
    expect(section).toContain('function InlineHelp')
    expect(section).toContain('group-hover/help:block')
    expect(section).toContain('启用关键词通道，对精确词匹配召回更友好')
    expect(section).toContain('用重排序模型对候选片段二次排序')
    expect(section).toContain('checked={isRerankerEnabled}')
    expect(section).toContain('onCheckedChange={(checked) =>')
    expect(section).not.toContain('ToggleLeft')
    expect(section).not.toContain('ToggleRight')
    expect(section).not.toContain('需要先在“重排序模型”里配置 Provider')
  })
})
