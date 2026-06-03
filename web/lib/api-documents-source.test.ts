import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document api service source', () => {
  it('keeps a real document service module instead of a passthrough re-export', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api/documents.ts'), 'utf8')

    expect(src).not.toContain("export { documentApi } from '@/lib/api-client'")
    expect(src).toContain('export const documentApi = {')
    expect(src).toContain("from '@/lib/api/core'")
    expect(src).toContain('openapiRequest({')
  })

  it('keeps api-client as a compatibility barrel instead of owning documentApi directly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api-client.ts'), 'utf8')

    expect(src).not.toContain('export const documentApi = {')
    expect(src).toContain("export { documentApi } from '@/lib/api/documents'")
  })

  it('uses the long API timeout for manual chunk ingestion', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api/documents.ts'), 'utf8')
    const manualIngestBlock = src.slice(src.indexOf('async createFromChunks'), src.indexOf('async chunkPreview'))

    expect(src).toContain("import { API_LONG_TIMEOUT_MS } from '@/lib/env'")
    expect(manualIngestBlock).toContain("path: '/api/v1/documents/manual'")
    expect(manualIngestBlock).toContain('timeoutMs: API_LONG_TIMEOUT_MS')
  })

  it('passes upload-only batch uploads through to the backend form field', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api/documents.ts'), 'utf8')
    const batchUploadBlock = src.slice(src.indexOf('async uploadBatch'), src.indexOf('async list('))

    expect(batchUploadBlock).toContain('upload_only?: boolean')
    expect(batchUploadBlock).toContain('if (options.upload_only)')
    expect(batchUploadBlock).toContain("formData.append('upload_only', 'true')")
  })
})
