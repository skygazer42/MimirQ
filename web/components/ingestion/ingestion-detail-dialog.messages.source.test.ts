import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { readMessageCatalogSource } from '@/lib/source-test-utils'

describe('ingestion detail dialog message sources', () => {
  it('moves ingestion detail copy into next-intl catalogs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'ingestion-detail-dialog.tsx'), 'utf8')
    const messagesSrc = readMessageCatalogSource(path.resolve(__dirname, '../..'))

    expect(src).toContain("useTranslations('IngestionDetailDialog')")
    expect(src).toContain('label: t(`stages.${stage.key}`)')
    expect(src).toContain('t("header.fallbackTitle")')
    expect(src).toContain('t("actions.retry")')
    expect(src).toContain('t("errors.diffFailed")')

    expect(messagesSrc).toContain("pending: '待处理'")
    expect(messagesSrc).toContain("processing: '处理中'")
    expect(messagesSrc).toContain("completed: '已完成'")
    expect(messagesSrc).toContain("pipeline: {\n      title: '处理流程'")
    expect(messagesSrc).toContain("progress: '进度'")
    expect(messagesSrc).toContain("title: '运行时详情'")
    expect(messagesSrc).toContain("documentId: '文档 ID'")
    expect(messagesSrc).toContain("datasetId: '数据集 ID'")
    expect(messagesSrc).toContain("fromLabel: '起始版本'")
    expect(messagesSrc).toContain("toLabel: '目标版本'")
    expect(messagesSrc).toContain("activeTag: '激活'")
  })
})
