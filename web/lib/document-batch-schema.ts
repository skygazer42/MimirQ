import { z } from 'zod'

import { integerSchema } from '@/lib/response-schema'

const documentBatchRetryResponseSchema = z.looseObject({
  queued: integerSchema.nonnegative(),
  skipped: integerSchema.nonnegative(),
  not_found: z.array(z.string().min(1)),
  denied: z.array(z.string().min(1)),
  conflicts: z.array(z.string().min(1)),
})

export type DocumentBatchRetryResponse = z.infer<typeof documentBatchRetryResponseSchema>

export function createDocumentBatchRetryResponseSchema(documentCount: number) {
  return documentBatchRetryResponseSchema.refine(
    (result) =>
      result.queued + result.skipped + result.not_found.length + result.denied.length + result.conflicts.length ===
      documentCount,
    { message: '批量重试回执数量与提交数量不一致' },
  )
}

const uploadFileResultFields = {
  filename: z.string(),
  source_path: z.string().nullish(),
}

const documentBatchUploadResponseSchema = z.looseObject({
  total: integerSchema.nonnegative(),
  successful_count: integerSchema.nonnegative(),
  failed_count: integerSchema.nonnegative(),
  successful: z.array(z.looseObject({ ...uploadFileResultFields, document_id: z.string().min(1), status: z.string() })),
  failed: z.array(z.looseObject({ ...uploadFileResultFields, error: z.string() })),
  precheck_scan_run_id: z.string().min(1).nullish(),
})

export function createDocumentBatchUploadResponseSchema(fileCount: number, precheckOnly: boolean) {
  return documentBatchUploadResponseSchema.refine(
    (result) => {
      if (
        result.total !== fileCount ||
        result.successful_count !== result.successful.length ||
        result.failed_count !== result.failed.length
      )
        return false

      // Precheck returns failures without creating documents for staged files.
      if (precheckOnly) return result.successful_count === 0 && result.failed_count <= fileCount
      return result.successful_count + result.failed_count === fileCount
    },
    { message: '批量上传回执数量与提交文件不一致' },
  )
}
