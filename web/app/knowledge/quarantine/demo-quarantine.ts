import type { Document } from '@/types'

function createDemoGovernance(
  dropReasons: Record<string, number>
): NonNullable<Document['governance']> {
  return {
    enabled: true,
    documents: 1,
    changed_documents: 0,
    rules_applied: Object.keys(dropReasons).length,
    dropped_documents: Object.values(dropReasons).some((count) => count > 0)
      ? 1
      : 0,
    drop_reasons: dropReasons,
  }
}

function createReviewedMetadata(): Document['metadata'] {
  return { user: { quarantine_reviewed: true } }
}

function getDemoDocumentStatus(index: number): Document['status'] {
  if (index >= 23 && index < 179) return 'completed'
  if (index < 23) return 'quarantined'
  return 'cancelled'
}

export function makeDemoQuarantineDocument(
  id: number,
  overrides: Partial<Document> & { filename: string; file_type: string }
): Document {
  const createdAt = new Date(
    Date.UTC(2026, 2, 31, 3, 0, 0) - id * 36 * 60_000
  ).toISOString()
  const updatedAt = new Date(
    Date.UTC(2026, 2, 31, 11, 45, 0) - id * 22 * 60_000
  ).toISOString()
  const { filename, file_type: fileType, ...restOverrides } = overrides

  return {
    id: `demo-q-${id.toString().padStart(4, '0')}`,
    tenant_id: 'demo-tenant',
    dataset_id: 'dataset-demo',
    filename,
    status: 'quarantined',
    file_type: fileType,
    file_size: 1_240_000,
    chunk_count: 0,
    processing_progress: 0,
    created_at: createdAt,
    updated_at: updatedAt,
    processed_at: updatedAt,
    current_stage: 'governance',
    error_message: '命中治理规则，待人工复核',
    metadata: {},
    governance: createDemoGovernance({}),
    ...restOverrides,
  } as Document
}

export function buildDemoQuarantineDocuments(): Document[] {
  const leadRows: Document[] = [
    makeDemoQuarantineDocument(1, {
      filename: '用户协议.pdf',
      file_type: 'pdf',
      file_size: 1.24 * 1024 * 1024,
      dataset_id: '文档解析',
      governance: createDemoGovernance({ pii_exceeded: 1 }),
      error_message: '包含手机号、身份证号等敏感信息',
      status: 'quarantined',
    }),
    makeDemoQuarantineDocument(2, {
      filename: '财务报表.xlsx',
      file_type: 'xlsx',
      file_size: 2.81 * 1024 * 1024,
      dataset_id: '数据导入',
      governance: createDemoGovernance({ outline_only: 1 }),
      error_message: '包含未公开财务数据',
      status: 'quarantined',
    }),
    makeDemoQuarantineDocument(3, {
      filename: '内部沟通记录.docx',
      file_type: 'docx',
      file_size: 860 * 1024,
      dataset_id: '文档解析',
      governance: createDemoGovernance({ pii_exceeded: 1 }),
      error_message: '包含内部人事及组织结构信息',
      status: 'quarantined',
    }),
    makeDemoQuarantineDocument(4, {
      filename: '会议纪要.pdf',
      file_type: 'pdf',
      file_size: 1.09 * 1024 * 1024,
      dataset_id: '文档解析',
      governance: createDemoGovernance({ low_density: 1 }),
      error_message: '包含手机号、身份证号等敏感信息',
      metadata: createReviewedMetadata(),
      status: 'quarantined',
    }),
    makeDemoQuarantineDocument(5, {
      filename: '产品蓝图.pptx',
      file_type: 'pptx',
      file_size: 3.45 * 1024 * 1024,
      dataset_id: '数据导入',
      governance: createDemoGovernance({ outline_only: 1 }),
      error_message: '包含未公开产品规划',
      metadata: createReviewedMetadata(),
      status: 'quarantined',
    }),
    makeDemoQuarantineDocument(6, {
      filename: '客户名单.csv',
      file_type: 'csv',
      file_size: 680 * 1024,
      dataset_id: 'API 接入',
      governance: createDemoGovernance({ pii_exceeded: 1 }),
      error_message: '包含个人隐私信息',
      metadata: createReviewedMetadata(),
      status: 'completed',
    }),
  ]

  const reasons = [
    {
      key: 'pii_exceeded',
      filename: '员工信息名录',
      fileType: 'docx',
      source: '文档解析',
      error: '包含手机号、身份证号等敏感信息',
    },
    {
      key: 'outline_only',
      filename: '项目大纲',
      fileType: 'pptx',
      source: '数据导入',
      error: '包含未公开产品规划',
    },
    {
      key: 'low_density',
      filename: '扫描件归档',
      fileType: 'pdf',
      source: '文档解析',
      error: '正文密度过低，建议人工复核',
    },
    {
      key: 'secrets_exceeded',
      filename: '环境变量清单',
      fileType: 'csv',
      source: 'API 接入',
      error: '疑似命中 token / secret',
    },
  ] as const

  const extraRows = Array.from({ length: 242 }, (_, index) => {
    const bucket = reasons[index % reasons.length]
    const status = getDemoDocumentStatus(index)
    const reviewed = status === 'completed'
    const suffix = `${String(index + 7).padStart(3, '0')}`
    return makeDemoQuarantineDocument(index + 7, {
      filename: `${bucket.filename}_${suffix}.${bucket.fileType}`,
      file_type: bucket.fileType,
      file_size: (0.68 + (index % 7) * 0.42) * 1024 * 1024,
      dataset_id: bucket.source,
      governance: createDemoGovernance({ [bucket.key]: 1 }),
      error_message: bucket.error,
      metadata: reviewed ? createReviewedMetadata() : {},
      status,
    })
  })

  return [...leadRows, ...extraRows]
}
