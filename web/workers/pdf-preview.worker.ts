import { expose } from 'comlink'

import { computePdfPreviewData } from '@/lib/pdf-preview-computation'

const api = {
  computePdfPreviewData,
}

export type PdfPreviewWorkerApi = typeof api

expose(api)
