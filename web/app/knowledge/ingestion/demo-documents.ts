import type { Document } from '@/types'

function createDemoDocument(overrides: Partial<Document>): Document {
  const now = new Date().toISOString()

  return {
    id: `demo-${Math.random().toString(36).slice(2, 10)}`,
    filename: 'demo.txt',
    file_type: 'txt',
    file_size: 0,
    status: 'pending',
    created_at: now,
    updated_at: now,
    chunk_count: 0,
    dataset_id: 'demo-dataset',
    current_stage: 'queued',
    error_message: null,
    metadata: {},
    ...overrides,
  } as Document
}

const FALLBACK_DEMO_DOCUMENTS: Document[] = [
  createDemoDocument({
    id: 'demo-md-ready',
    filename: 'employee-handbook.md',
    file_type: 'md',
    file_size: 182_400,
    status: 'completed',
    chunk_count: 28,
    dataset_id: 'hr-knowledge',
    current_stage: 'completed',
  }),
  createDemoDocument({
    id: 'demo-pdf-processing',
    filename: 'scanned-invoice-batch.pdf',
    file_type: 'pdf',
    file_size: 3_820_000,
    status: 'processing',
    chunk_count: 0,
    dataset_id: 'finance-ops',
    current_stage: 'parsing',
    processing_progress: 48,
  }),
  createDemoDocument({
    id: 'demo-pdf-failed',
    filename: 'supplier-contract.pdf',
    file_type: 'pdf',
    file_size: 1_640_000,
    status: 'failed',
    chunk_count: 0,
    dataset_id: 'legal-review',
    current_stage: 'chunking',
    error_message: 'ParserTimeout: OCR worker exceeded soft limit',
  }),
  createDemoDocument({
    id: 'demo-xlsx-quarantined',
    filename: 'customer-export.xlsx',
    file_type: 'xlsx',
    file_size: 640_000,
    status: 'quarantined',
    chunk_count: 0,
    dataset_id: 'sales-ops',
    current_stage: 'governance',
    error_message: 'PII_DETECTED',
  }),
  createDemoDocument({
    id: 'demo-html-pending',
    filename: 'partner-portal.html',
    file_type: 'html',
    file_size: 214_000,
    status: 'pending',
    chunk_count: 0,
    dataset_id: 'partner-site',
    current_stage: 'queued',
  }),
]

export function buildDemoDocuments(documents: Document[]): Document[] {
  if (documents.length > 0) {
    return documents.slice(0, 8).map((doc) => ({
      ...doc,
      status: doc.status === 'completed' ? 'completed' : doc.status,
    }))
  }

  return FALLBACK_DEMO_DOCUMENTS.map((doc) => ({ ...doc }))
}
