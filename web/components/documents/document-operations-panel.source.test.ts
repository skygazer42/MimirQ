import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('DocumentOperationsPanel source', () => {
  it('surfaces document stats, batch, metadata, duplicate, image and batch-upload APIs explicitly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-operations-panel.tsx'), 'utf8')

    for (const api of [
      'documentApi.stats',
      'documentApi.getParsedContent',
      'documentApi.batchUpdateAccess',
      'documentApi.batchMove',
      'documentApi.listDuplicates',
      'documentApi.getLifecycleMetadata',
      'documentApi.batchPatchUserMetadata',
      'documentApi.applyBatchUploadUrls',
      'documentApi.getBatchTaskStatus',
      'documentApi.fetchImage',
      'documentApi.fetchImageByImgId',
    ]) {
      expect(src).toContain(api)
    }
  })

  it('binds operator actions to the current dataset and selected documents by default', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-operations-panel.tsx'), 'utf8')

    expect(src).toContain('datasets?: Dataset[]')
    expect(src).toContain('const [advancedOpen, setAdvancedOpen] = useState(false)')
    expect(src).toContain('currentDatasetLabel')
    expect(src).toContain('使用当前知识库和勾选文档')
    expect(src).toContain('移动到知识库')
    expect(src).toContain('targetDatasetOptions.map')
    expect(src).toContain('高级覆盖（可选）')
  })

  it('keeps raw backend JSON hidden until an operation has a result', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-operations-panel.tsx'), 'utf8')

    expect(src).toContain('const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)')
    expect(src).toContain('const [resultDetailsOpen, setResultDetailsOpen] = useState(false)')
    expect(src).toContain('formatResultSummary')
    expect(src).toContain('查看原始响应')
    expect(src).toContain('{result ? (')
    expect(src).not.toContain('等待执行文档统计、批量权限/移动、元数据、图片或批量上传任务操作')
  })
})
