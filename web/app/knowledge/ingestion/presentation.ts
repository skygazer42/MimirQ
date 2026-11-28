import type { DatasetPrecheckFileOut, Document } from '@/types'

import { estimatePdfPageCountFromSignals, getDocumentRuntimeStats, stringifyForDisplay } from './document-signals'
export type StatusToneResult = {
  label: string
  tone: string
}

type BatchProfileFile = {
  blockCount: number
  chars: number
  fileSize: number
  fileType: string
  imageCount: number
  pageCountEstimated: boolean
  pdfPages: number
  tableCount: number
}

export function getQueueOutcomeReason(item: { reason?: unknown }, ok: boolean): string {
  const reason = stringifyForDisplay(item.reason)
  if (reason) return reason
  if (ok) return '任务完成'
  return '任务失败或被跳过'
}

export function getRecentLogDetail(status: string, filename: string): string {
  switch (status) {
    case 'failed':
      return `解析失败：${filename}`
    case 'completed':
      return `解析成功：${filename}`
    case 'quarantined':
      return `已隔离：${filename}`
    case 'cancelled':
      return `已取消：${filename}`
    case 'pending':
      return `等待处理：${filename}`
    case 'processing':
      return `处理中：${filename}`
    default:
      return `${getDocumentStatusLabel(status)}：${filename}`
  }
}

export function resolveFallbackComplexity({
  durationP90,
  executionFailureRate,
  pdfRatio,
  totalCharacters,
  totalSizeBytes,
}: Readonly<{
  durationP90: number | null
  executionFailureRate: number
  pdfRatio: number
  totalCharacters: number
  totalSizeBytes: number
}>): '高' | '中' | '低' {
  if (pdfRatio >= 0.35 || executionFailureRate >= 8 || (durationP90 !== null && durationP90 >= 20)) {
    return '高'
  }
  if (pdfRatio >= 0.12 || totalSizeBytes >= 500 * 1024 * 1024 || totalCharacters >= 500_000) {
    return '中'
  }
  return '低'
}

export function formatPdfPageAverageLabel({
  avgPdfPages,
  hasEstimatedPdfPages,
  hasPdfProfiles,
}: Readonly<{
  avgPdfPages: number
  hasEstimatedPdfPages: boolean
  hasPdfProfiles: boolean
}>): string {
  if (avgPdfPages) {
    const estimatedSuffix = hasEstimatedPdfPages ? '估算' : ''
    return `${Math.round(avgPdfPages)} 页${estimatedSuffix}`
  }
  if (hasPdfProfiles) return '暂无页数'
  return '无 PDF'
}

export function formatStructureAverageLabel({
  avgPdfBlocks,
  avgPdfTables,
  hasPdfProfiles,
}: Readonly<{
  avgPdfBlocks: number
  avgPdfTables: number
  hasPdfProfiles: boolean
}>): string {
  if (!hasPdfProfiles) return '无 PDF'
  if (avgPdfTables) return `${Math.round(avgPdfTables)} 表`
  return `${Math.round(avgPdfBlocks).toLocaleString()} 块`
}

export function getDocumentStatusLabel(status: string | null | undefined): string {
  switch (status) {
    case 'completed':
      return '已完成'
    case 'failed':
      return '失败'
    case 'quarantined':
      return '已隔离'
    case 'cancelled':
      return '已取消'
    case 'processing':
      return '处理中'
    case 'pending':
      return '等待中'
    default:
      return status ?? '未开始'
  }
}

export function getDocumentStatusTone(status: string | null | undefined): string {
  switch (status) {
    case 'completed':
      return 'text-success'
    case 'failed':
      return 'text-rose'
    case 'processing':
      return 'text-info dark:text-foreground'
    case 'quarantined':
      return 'text-warning'
    default:
      return 'text-muted-foreground'
  }
}

export function buildPrecheckProfileFile(file: DatasetPrecheckFileOut): BatchProfileFile {
  const pageCount = file.pdf_pages?.page_count ?? 0
  const shouldEstimatePageCount = file.file_type.toLowerCase() === 'pdf' && pageCount === 0
  return {
    chars: file.text_characters,
    fileSize: file.file_size,
    fileType: file.file_type,
    pdfPages: shouldEstimatePageCount
      ? estimatePdfPageCountFromSignals({ characters: file.text_characters, fileSize: file.file_size })
      : pageCount,
    pageCountEstimated: shouldEstimatePageCount,
    imageCount: 0,
    tableCount: 0,
    blockCount: 0,
  }
}

export function buildDocumentProfileFile(document: Document): BatchProfileFile {
  const { pageCount, blockCount, imageCount, tableCount } = getDocumentRuntimeStats(document)
  const shouldEstimatePageCount = document.file_type.toLowerCase() === 'pdf' && pageCount === 0
  const characters = document.total_characters

  return {
    blockCount,
    chars: characters,
    fileSize: document.file_size,
    fileType: document.file_type,
    imageCount,
    pageCountEstimated: shouldEstimatePageCount,
    pdfPages: shouldEstimatePageCount
      ? estimatePdfPageCountFromSignals({
          characters,
          fileSize: document.file_size,
        })
      : pageCount,
    tableCount,
  }
}
