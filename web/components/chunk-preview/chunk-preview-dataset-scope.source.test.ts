import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const sidebar = fs.readFileSync(
  path.resolve(__dirname, 'components/workbench/sidebar-client.tsx'),
  'utf8'
)
const messages = fs.readFileSync(
  path.resolve(__dirname, '../../i18n/messages/zh-CN/chunk-preview.ts'),
  'utf8'
)

describe('chunk preview dataset scope', () => {
  it('preserves scope, file selection, batch ingestion and recommendation behavior', () => {
    expect(sidebar).toContain(
      "setDatasetId(value === DATASET_DEFAULT_VALUE ? '' : value)"
    )
    expect(sidebar).toContain('setCurrentFileIndex(fileIndex)')
    expect(sidebar).toContain('toggleIngestFileSelection(f.id)')
    expect(sidebar).toContain('onClick={submitSelectedFiles}')
    expect(sidebar).toContain('pipelineApi.ingestionPreview(currentFile')
    expect(sidebar).toContain('applyPipelinePatch(selectedDataset.pipeline')
  })

  it('uses one panel with three flat sections instead of nested cards', () => {
    expect(sidebar).toContain(
      '<SidebarPanel tone="sky" className="relative overflow-hidden p-0">'
    )
    expect(sidebar).toContain('data-dataset-scope-header="true"')
    expect(sidebar).toContain('data-dataset-scope-selector="true"')
    expect(sidebar).toContain(
      'data-chunk-file-queue\n            className="border-t border-foreground/10 px-3 py-3"'
    )
    expect(sidebar).toContain(
      'className="mt-2 max-h-[216px] space-y-1 overflow-y-auto overscroll-contain no-scrollbar"'
    )
    expect(sidebar).toContain(
      'className="mt-2 flex items-center justify-between gap-2 border-t border-foreground/10 pt-2"'
    )
    expect(sidebar).not.toContain('Knowledge Context')
    expect(sidebar).not.toContain(
      'rounded-2xl border border-border/45 bg-background/70 p-2 shadow-none'
    )
    expect(sidebar).not.toContain(
      'rounded-xl border border-dashed border-border/60 bg-muted/20 px-3 py-4 text-center'
    )
    expect(sidebar).not.toContain(
      'h-px bg-[linear-gradient(90deg,transparent,hsl(var(--border)/0.6),transparent)]'
    )
  })

  it('uses concise Chinese scope and empty-state copy', () => {
    expect(messages).toContain("title: '数据范围'")
    expect(messages).toContain("defaultOption: '解析工作区与数据集'")
    expect(messages).toContain(
      "hint: '默认显示解析工作区；选择数据集后查看已入库文档。'"
    )
    expect(messages).toContain("emptyAll: '解析工作区暂无文档'")
    expect(messages).not.toContain("title: 'Dataset Scope'")
  })
})
