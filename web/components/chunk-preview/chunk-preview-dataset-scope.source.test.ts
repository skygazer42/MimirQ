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
