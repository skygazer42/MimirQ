'use client'

import { useLayoutEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { reportApi } from '@/lib/api/reports'
import { formatApiBlobError } from '@/lib/api-errors'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { reportClientError } from '@/lib/client-logging'
import { downloadBlob } from '@/lib/download'
import { reportExportParams, reportPipelineSuffix } from './report-export'

const MAX_EXPORT_ERROR_BYTES = 1_048_576

const REPORT_EXPORTS = {
  json: {
    load: reportApi.exportDatasetReportJson,
    stem: 'report',
    extension: 'json',
    errorMessage: '导出 JSON 报告失败',
  },
  html: {
    load: reportApi.exportDatasetReportHtml,
    stem: 'report',
    extension: 'html',
    errorMessage: '导出 HTML 报告失败',
  },
  ragAudit: {
    load: reportApi.exportDatasetRagAuditHtml,
    stem: 'rag_audit',
    extension: 'html',
    errorMessage: '导出 RAG 审计报告失败',
  },
  bundle: {
    load: reportApi.exportDatasetReportBundleZip,
    stem: 'report-bundle',
    extension: 'zip',
    errorMessage: '导出完整归档包失败',
  },
} as const
export type ReportExportKind = keyof typeof REPORT_EXPORTS

export function useReportExports({
  sessionKey,
  datasetId,
  pipelineHash,
  connectorRunsLimit,
  redact,
}: Readonly<{
  sessionKey: string
  datasetId: string
  pipelineHash: string
  connectorRunsLimit: number
  redact: boolean
}>) {
  const [exporting, setExporting] = useState<ReportExportKind | null>(null)
  const ownerRef = useRef({ active: true })
  const exportRequest = useRef<AbortController | null>(null)
  useLayoutEffect(() => {
    const owner = { active: true }
    ownerRef.current = owner
    setExporting(null)
    return () => {
      owner.active = false
      exportRequest.current?.abort()
      exportRequest.current = null
    }
  }, [sessionKey, datasetId, pipelineHash, connectorRunsLimit, redact])

  async function exportReport(kind: ReportExportKind) {
    const owner = ownerRef.current
    if (datasetId.length === 0 || exportRequest.current !== null || !owner.active || getAuthSessionKey() !== sessionKey)
      return
    const controller = new AbortController()
    exportRequest.current = controller
    setExporting(kind)
    const format = REPORT_EXPORTS[kind]
    const params = reportExportParams(pipelineHash, connectorRunsLimit, kind === 'json' ? undefined : redact)
    function isCurrent() {
      return (
        owner.active &&
        ownerRef.current === owner &&
        exportRequest.current === controller &&
        getAuthSessionKey() === sessionKey
      )
    }
    try {
      const blob = await format.load(datasetId, params, { signal: controller.signal })
      if (!isCurrent()) return
      const isRedactedExport = kind !== 'json' && redact
      const filename = isRedactedExport
        ? `dataset.${format.stem}.${format.extension}`
        : `${datasetId}.${format.stem}${reportPipelineSuffix(pipelineHash)}.${format.extension}`
      downloadBlob(filename, blob)
      toast.success('报告已开始下载')
    } catch (error) {
      if (!isCurrent()) return
      reportClientError(format.errorMessage, error)
      const message = await formatApiBlobError(error, format.errorMessage, MAX_EXPORT_ERROR_BYTES)
      if (isCurrent()) toast.error(message)
    } finally {
      if (exportRequest.current === controller) {
        exportRequest.current = null
        if (owner.active && getAuthSessionKey() === sessionKey) setExporting(null)
      }
    }
  }

  return { exporting, exportReport }
}
