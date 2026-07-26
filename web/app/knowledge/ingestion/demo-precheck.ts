import type {
  DatasetPrecheckFileOut,
  DatasetPrecheckNearDupResponse,
  DatasetPrecheckSamplesResponse,
  DatasetPrecheckSummary,
  Document,
} from '@/types'

export function anonymizeEvidenceName(name: string): string {
  const value = String(name || '')
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + (value.codePointAt(index) ?? 0)) >>> 0
  }
  return `FILE_${hash.toString(36).toUpperCase().padStart(6, '0').slice(-6)}`
}

export function buildDemoPrecheckSummary(
  documents: Document[]
): DatasetPrecheckSummary {
  return {
    dataset_id: 'demo-dataset',
    scan_run_id: 'demo-run',
    generated_at: new Date().toISOString(),
    total_files: 12_543,
    total_size_bytes: Math.round(48.6 * 1024 * 1024 * 1024),
    by_file_type: { pdf: 7_854, docx: 2_112, xlsx: 1_420, pptx: 633, md: 524 },
    file_size_histogram: [
      { label: '<500KB', count: 3521 },
      { label: '500KB-2MB', count: 4873 },
      { label: '2MB-5MB', count: 2536 },
      { label: '5MB-10MB', count: 1140 },
      { label: '>10MB', count: 473 },
    ],
    length_percentiles: {
      p25: 812,
      p50: 1_876,
      p75: 5_314,
      p90: 9_816,
      p99: 23_654,
    },
    length_histogram: [
      { label: '<1k', count: 382 },
      { label: '1k-2k', count: 958 },
      { label: '2k-5k', count: 1731 },
      { label: '5k-10k', count: 1118 },
      { label: '10k-20k', count: 624 },
      { label: '20k-50k', count: 218 },
      { label: '50k-100k', count: 66 },
      { label: '>100k', count: 14 },
    ],
    pdf_scan: {
      scanned: 911,
      not_scanned: 8_645,
      unknown: 2_987,
    },
    pdf_detection: {
      text: 8_645,
      mixed: 2_987,
      scan: 911,
    },
    pii_hits_total: { phone: 524, email: 58, id_card: 19 },
    secrets_hits_total: {},
    findings: [
      {
        key: 'pdf_scanned',
        label: '扫描件',
        severity: 'warning',
        count: 1_956,
      },
      { key: 'parse_failed', label: '解析失败', severity: 'error', count: 412 },
      { key: 'pii', label: '合敏感信息', severity: 'warning', count: 736 },
      { key: 'exact_dup', label: '重复文件', severity: 'info', count: 1_128 },
      { key: 'near_dup', label: '版本冲突', severity: 'info', count: 342 },
      { key: 'other', label: '其他风险', severity: 'info', count: 289 },
    ],
  }
}

export function buildDemoPrecheckSamples(
  documents: Document[]
): DatasetPrecheckSamplesResponse {
  const fileItems: DatasetPrecheckFileOut[] = [
    {
      name: '财务报表_2024Q1.pdf',
      file_type: 'pdf',
      file_size: Math.round(138.5 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 220,
      estimated_text: false,
      pdf_scanned: true,
      pdf_pages: {
        page_count: 84,
        sampled_pages: 10,
        scanned_pages: 77,
        text_pages: 5,
        low_density_pages: 2,
        unknown_pages: 0,
        scan_ratio: 0.92,
        low_density_ratio: 0.02,
      },
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['pdf_scanned'],
      error_message: null,
    },
    {
      name: '员工手册_最新版.docx',
      file_type: 'docx',
      file_size: Math.round(24.3 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 12430,
      estimated_text: false,
      pdf_scanned: null,
      pdf_pages: null,
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['exact_dup', 'near_dup'],
      error_message: null,
    },
    {
      name: '合同_2024_v3.docx',
      file_type: 'docx',
      file_size: Math.round(12.7 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 9816,
      estimated_text: false,
      pdf_scanned: null,
      pdf_pages: null,
      spreadsheet: null,
      pii_hits: { phone: 2, email: 1 },
      secrets_hits: {},
      findings: ['pii'],
      error_message: null,
    },
    {
      name: '技术方案_无_汇总.pdf',
      file_type: 'pdf',
      file_size: Math.round(56.8 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 2310,
      estimated_text: false,
      pdf_scanned: false,
      pdf_pages: {
        page_count: 48,
        sampled_pages: 10,
        scanned_pages: 8,
        text_pages: 34,
        low_density_pages: 6,
        unknown_pages: 0,
        scan_ratio: 0.17,
        low_density_ratio: 0.12,
      },
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['near_dup'],
      error_message: null,
    },
    {
      name: '项目计划_需求.pptx',
      file_type: 'pptx',
      file_size: Math.round(18.2 * 1024 * 1024),
      file_mtime: Date.now(),
      text_characters: 1642,
      estimated_text: false,
      pdf_scanned: null,
      pdf_pages: null,
      spreadsheet: null,
      pii_hits: {},
      secrets_hits: {},
      findings: ['parse_failed'],
      error_message: '文档暂时解析失败',
    },
  ]

  return {
    requested: 5,
    strata_count: 4,
    representative: fileItems.slice(0, 3),
    needs_review: {
      pdf_scanned: fileItems.filter((file) =>
        file.findings.includes('pdf_scanned')
      ),
      parse_failed: fileItems.filter((file) =>
        file.findings.includes('parse_failed')
      ),
      pii: fileItems.filter((file) => file.findings.includes('pii')),
    },
    top_large_files: [...fileItems]
      .sort((left, right) => right.file_size - left.file_size)
      .slice(0, 5),
    top_long_text: [...fileItems]
      .sort((left, right) => right.text_characters - left.text_characters)
      .slice(0, 5),
  }
}

export function buildDemoNearDupResponse(): DatasetPrecheckNearDupResponse {
  return {
    threshold: 5,
    max_pairs: 20,
    pairs_returned: 2,
    clusters_returned: 1,
    clusters: [
      { id: 'demo-cluster-1', members: ['FILE_00A1BC', 'FILE_00A1BD'] },
    ],
    pairs: [
      { a: 'FILE_00A1BC', b: 'FILE_00A1BD', distance: 2 },
      { a: 'FILE_00A1BE', b: 'FILE_00A1BF', distance: 3 },
    ],
  }
}
