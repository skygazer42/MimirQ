'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, BarChart3, Download, FileUp, History, Loader2, Plus, RefreshCw, Save, Scissors, Settings2, Sparkles, Table2, Trash2 } from 'lucide-react'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'

import { datasetApi, pipelineApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES } from '@/lib/chunk-strategies'
import { PARSER_BACKEND_REGISTRY_OPTIONS } from '@/lib/parser-options'
import { queryKeys } from '@/lib/query-keys'
import { randomBase36Id } from '@/lib/secure-random'
import { cn, detachPromise } from '@/lib/utils'
import { useRouter } from '@/i18n/navigation'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import type {
  IngestionPolicy,
  IngestionRule,
  IngestionPreviewResponse,
} from '@/types'

const NONE = '__none__'
const INGESTION_PROFILE_PARAMS = { include_builtin: true, limit: 200 } as const

const PREPROCESS_STEP_CATALOG: Array<{ id: string; label: string; desc: string }> = [
  { id: 'text.reencode_utf8', label: '文本编码修复 → UTF-8', desc: '修复乱码/编码不一致（GBK/Windows-1252 等）' },
  { id: 'text.strip_bom', label: '移除 BOM', desc: '修复 UTF-8 BOM 导致的首行异常' },
  { id: 'text.normalize_newlines', label: '统一换行符', desc: 'CRLF/CR → LF，减少解析噪声' },
  { id: 'text.collapse_blank_lines', label: '压缩连续空行', desc: '把 3+ 连续空行压缩为最多 2 行，降低噪声' },
  { id: 'text.trim_trailing_whitespace', label: '去掉行尾空格', desc: '减少 diff 抖动与无意义字符' },
  { id: 'text.remove_zero_width', label: '移除零宽字符/软连字符', desc: '修复网页/扫描/OCR/PDF 文本中常见的隐藏字符' },
  { id: 'text.remove_control_chars', label: '移除控制字符', desc: String.raw`去掉 \x00 等控制字符（保留 TAB/LF/CR）` },
  { id: 'text.normalize_unicode_nfc', label: 'Unicode 规范化（NFC）', desc: '更保守的 Unicode 归一（比 NFKC 更少语义风险）' },
  { id: 'text.normalize_unicode_nfkc', label: 'Unicode 规范化（NFKC）', desc: '全角/半角与兼容字符归一（谨慎启用）' },
  { id: 'html.strip_scripts_styles', label: 'HTML：移除 script/style', desc: '减少网页样板/脚本注入噪声' },
  { id: 'html.strip_comments', label: 'HTML：移除注释', desc: '减少抓取页面的注释噪声' },
  { id: 'html.strip_boilerplate_tags', label: 'HTML：移除导航/页眉页脚', desc: '移除 nav/header/footer/aside/noscript 等常见样板区块' },
]

type IngestionPolicyTemplate = {
  key: string
  name: string
  description: string
  tags: string[]
  // The id will be generated when applying the template.
  rules: Array<Omit<IngestionRule, 'id'>>
}

const INGESTION_POLICY_TEMPLATES: IngestionPolicyTemplate[] = [
  {
    key: 'recommended:kb_general',
    name: '推荐：通用知识库（HTML / PDF / Office / Text）',
    description: '覆盖最常见入库来源，默认搭配内置治理预设；规则可再按需微调与调序。',
    tags: ['HTML', 'PDF', 'Office', 'MD/TXT', 'builtin profiles'],
    rules: [
      {
        name: '网页 HTML（去样板/去导航）',
        enabled: true,
        match: { extensions: ['.html', '.htm'], filename_regex: null },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'html.strip_scripts_styles', params: {} },
            { id: 'html.strip_comments', params: {} },
            { id: 'html.strip_boilerplate_tags', params: {} },
            { id: 'text.normalize_newlines', params: {} },
            { id: 'text.collapse_blank_lines', params: {} },
            { id: 'text.trim_trailing_whitespace', params: {} },
            { id: 'text.remove_zero_width', params: {} },
            { id: 'text.remove_control_chars', params: {} },
          ],
        },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:html_web',
        pipeline_patch: {},
      },
      {
        name: 'PDF 文本版（修复断行/页眉页脚）',
        enabled: true,
        match: { extensions: ['.pdf'], filename_regex: null },
        preprocess: { enabled: false, steps: [] },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:pdf_text',
        pipeline_patch: {},
      },
      {
        name: 'Office（DOCX/PPTX/XLSX）',
        enabled: true,
        match: { extensions: ['.docx', '.pptx', '.xls', '.xlsx'], filename_regex: null },
        preprocess: { enabled: false, steps: [] },
        parser_backend: 'markitdown',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:kb_default',
        pipeline_patch: {},
      },
      {
        name: 'Markdown / 纯文本（保守清洗）',
        enabled: true,
        match: { extensions: ['.md', '.txt', '.log'], filename_regex: null },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'text.reencode_utf8', params: {} },
            { id: 'text.strip_bom', params: {} },
            { id: 'text.normalize_newlines', params: {} },
            { id: 'text.trim_trailing_whitespace', params: {} },
            { id: 'text.remove_zero_width', params: {} },
            { id: 'text.remove_control_chars', params: {} },
          ],
        },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:kb_default',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:pdf_ocr_first',
    name: 'PDF：扫描/OCR 优先（文件名命中 scan/ocr/扫描）',
    description: '先匹配可能是扫描/OCR 的 PDF（更强容错），否则走文本版 PDF 规则。',
    tags: ['PDF', 'OCR', 'two-step'],
    rules: [
      {
        name: 'PDF 扫描/OCR（优先）',
        enabled: true,
        match: { extensions: ['.pdf'], filename_regex: '(?i)(scan|ocr|扫描|影印|图片)' },
        preprocess: { enabled: false, steps: [] },
        parser_backend: 'deepdoc',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:pdf_scanned_ocr',
        pipeline_patch: {},
      },
      {
        name: 'PDF 文本（默认）',
        enabled: true,
        match: { extensions: ['.pdf'], filename_regex: null },
        preprocess: { enabled: false, steps: [] },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:pdf_text',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:web_scrape',
    name: '网页抓取（HTML）',
    description: '适用于抓取/复制网页：去样板/去导航/去追踪参，保留正文信息密度。',
    tags: ['HTML', 'boilerplate'],
    rules: [
      {
        name: '网页 HTML（抓取）',
        enabled: true,
        match: { extensions: ['.html', '.htm'], filename_regex: null },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'html.strip_scripts_styles', params: {} },
            { id: 'html.strip_comments', params: {} },
            { id: 'text.normalize_newlines', params: {} },
          ],
        },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:html_web',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:wiki_longform',
    name: '长文/Wiki/手册（去重+参考文献）',
    description: '适用于 Wiki/手册类长文：去重重复段落、保守裁剪 References、修复断行。',
    tags: ['Markdown', 'longform'],
    rules: [
      {
        name: '长文/Wiki（Markdown）',
        enabled: true,
        match: { extensions: ['.md'], filename_regex: null },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'text.strip_bom', params: {} },
            { id: 'text.normalize_newlines', params: {} },
            { id: 'text.trim_trailing_whitespace', params: {} },
          ],
        },
        parser_backend: 'markdown',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:wiki_longform',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:pii_compliance',
    name: '合规脱敏（PII/密钥）',
    description: '适用于可能包含邮箱/电话/Token 的文档：启用匿名化与密钥脱敏（mask）。',
    tags: ['PII', 'secrets'],
    rules: [
      {
        name: '合规脱敏（文本类）',
        enabled: true,
        match: { extensions: ['.md', '.txt', '.log', '.html', '.htm', '.csv', '.json'], filename_regex: null },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'text.reencode_utf8', params: {} },
            { id: 'text.strip_bom', params: {} },
            { id: 'text.normalize_newlines', params: {} },
          ],
        },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:legal_compliance',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:code_repo',
    name: '代码仓库（源码/配置/README）',
    description: '适用于源码/配置/README：保留换行与缩进，去掉代码块行号，并做 secrets 脱敏。',
    tags: ['code', 'configs', 'secrets'],
    rules: [
      {
        name: '代码仓库（源码/配置）',
        enabled: true,
        match: {
          extensions: [
            '.md', '.txt',
            '.py', '.js', '.ts', '.tsx',
            '.java', '.go', '.rs',
            '.c', '.cpp', '.h', '.hpp',
            '.cs', '.php', '.rb', '.sh',
            '.yml', '.yaml', '.toml', '.ini', '.cfg', '.conf', '.env',
            '.sql',
          ],
          filename_regex: null,
        },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'text.reencode_utf8', params: {} },
            { id: 'text.strip_bom', params: {} },
            { id: 'text.normalize_newlines', params: {} },
            { id: 'text.trim_trailing_whitespace', params: {} },
            { id: 'text.remove_control_chars', params: {} },
            { id: 'text.remove_zero_width', params: {} },
          ],
        },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:code_repo',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:structured_data',
    name: '结构化数据（CSV / JSON）',
    description: '适用于 CSV/JSON：保留行边界，轻量去噪；解析后更适合检索。',
    tags: ['csv', 'json'],
    rules: [
      {
        name: 'CSV（行式）',
        enabled: true,
        match: { extensions: ['.csv'], filename_regex: null },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'text.reencode_utf8', params: {} },
            { id: 'text.strip_bom', params: {} },
            { id: 'text.normalize_newlines', params: {} },
            { id: 'text.remove_control_chars', params: {} },
          ],
        },
        parser_backend: 'csv',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:structured_data',
        pipeline_patch: {},
      },
      {
        name: 'JSON / JSONL（pretty-print）',
        enabled: true,
        match: { extensions: ['.json'], filename_regex: null },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'text.reencode_utf8', params: {} },
            { id: 'text.strip_bom', params: {} },
            { id: 'text.normalize_newlines', params: {} },
            { id: 'text.remove_control_chars', params: {} },
          ],
        },
        parser_backend: 'json',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:structured_data',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:tables_tag_auto',
    name: '表格（CSV / XLSX）：TAG 自动分流（大表→SQL，小表→RAG）',
    description: '适用于既有小表也有大表：小表按文本解析入库；大表走 Table Store（SQLite）用于 SQL/NL→SQL。',
    tags: ['csv', 'xlsx', 'TAG', 'auto route'],
    rules: [
      {
        name: '表格 CSV（自动分流）',
        enabled: true,
        match: { extensions: ['.csv'], filename_regex: null },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'text.reencode_utf8', params: {} },
            { id: 'text.strip_bom', params: {} },
            { id: 'text.normalize_newlines', params: {} },
          ],
        },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:structured_data',
        pipeline_patch: {
          table_store_enabled: true,
          table_store_auto_route: true,
          table_store_auto_row_threshold: 5000,
          table_store_auto_col_threshold: 80,
          table_store_auto_sheet_threshold: 5,
          table_store_auto_file_bytes_threshold: 5000000,
        },
      },
      {
        name: '表格 XLS/XLSX（自动分流）',
        enabled: true,
        match: { extensions: ['.xls', '.xlsx'], filename_regex: null },
        preprocess: { enabled: false, steps: [] },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:structured_data',
        pipeline_patch: {
          table_store_enabled: true,
          table_store_auto_route: true,
          table_store_auto_row_threshold: 5000,
          table_store_auto_col_threshold: 80,
          table_store_auto_sheet_threshold: 5,
          table_store_auto_file_bytes_threshold: 5000000,
        },
      },
    ],
  },
  {
    key: 'recommended:metadata_enrich',
    name: '元数据增强（frontmatter/语言/关键词）',
    description: '适用于需要更强检索/筛选的文档：抽取关键词、语言检测、frontmatter 元数据。',
    tags: ['keywords', 'language', 'frontmatter'],
    rules: [
      {
        name: 'Markdown / 文本（元数据增强）',
        enabled: true,
        match: { extensions: ['.md', '.txt'], filename_regex: null },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'text.reencode_utf8', params: {} },
            { id: 'text.strip_bom', params: {} },
            { id: 'text.normalize_newlines', params: {} },
            { id: 'text.trim_trailing_whitespace', params: {} },
          ],
        },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:metadata_enrich',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:quality_gate',
    name: '质量门禁（低质量 → 隔离）',
    description: '适用于批量入库：对疑似无正文/低密度文档进行过滤并进入隔离队列，减少污染知识库。',
    tags: ['quality gate', 'quarantine'],
    rules: [
      {
        name: '质量门禁（PDF/HTML/文本）',
        enabled: true,
        match: { extensions: ['.pdf', '.html', '.htm', '.md', '.txt'], filename_regex: null },
        preprocess: { enabled: false, steps: [] },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:quality_gate_quarantine',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:html_xpath',
    name: '网页 XPath 定位正文（默认 //main）',
    description: '适用于结构稳定的网站：优先用 XPath 抽正文；可在规则里改成 //article 等。',
    tags: ['html', 'xpath'],
    rules: [
      {
        name: '网页 HTML（XPath）',
        enabled: true,
        match: { extensions: ['.html', '.htm'], filename_regex: null },
        preprocess: {
          enabled: true,
          steps: [
            { id: 'html.strip_scripts_styles', params: {} },
            { id: 'html.strip_comments', params: {} },
            { id: 'text.normalize_newlines', params: {} },
          ],
        },
        parser_backend: 'auto',
        chunk_strategy: null,
        governance_profile_ref: 'builtin:html_xpath_main',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:pdf_layout_tables',
    name: 'PDF（表格/版式优先）',
    description: '适用于表格/排版复杂 PDF：使用 docling 解析 + 表格规范化清洗。',
    tags: ['pdf', 'tables', 'layout'],
    rules: [
      {
        name: 'PDF（docling）',
        enabled: true,
        match: { extensions: ['.pdf'], filename_regex: null },
        preprocess: { enabled: false, steps: [] },
        parser_backend: 'docling',
        chunk_strategy: 'pdf_layout',
        governance_profile_ref: 'builtin:pdf_text',
        pipeline_patch: {},
      },
    ],
  },
  {
    key: 'recommended:legal_docs',
    name: '法律/合同（integrated_laws + 合规脱敏）',
    description: '适用于合同/法规：切块策略选择 integrated_laws，并启用 PII/密钥脱敏（可按需关闭）。',
    tags: ['legal', 'integrated_laws', 'pii'],
    rules: [
      {
        name: '法律 PDF（integrated_laws）',
        enabled: true,
        match: { extensions: ['.pdf'], filename_regex: null },
        preprocess: { enabled: false, steps: [] },
        parser_backend: 'auto',
        chunk_strategy: 'integrated_laws',
        governance_profile_ref: 'builtin:pdf_text',
        pipeline_patch: {
          "governance_pii_anonymize": true,
          "governance_pii_mode": "mask",
          "governance_pii_mask": "[REDACTED]",
          "governance_secrets_redact": true,
          "governance_secrets_mode": "mask",
          "governance_secrets_mask": "[SECRET]",
        },
      },
      {
        name: '法律 DOCX（integrated_laws）',
        enabled: true,
        match: { extensions: ['.docx'], filename_regex: null },
        preprocess: { enabled: false, steps: [] },
        parser_backend: 'markitdown',
        chunk_strategy: 'integrated_laws',
        governance_profile_ref: 'builtin:kb_default',
        pipeline_patch: {
          "governance_pii_anonymize": true,
          "governance_pii_mode": "mask",
          "governance_pii_mask": "[REDACTED]",
          "governance_secrets_redact": true,
          "governance_secrets_mode": "mask",
          "governance_secrets_mask": "[SECRET]",
        },
      },
    ],
  },
]

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function safeIdFromNow() {
  return `rule-${Date.now().toString(36)}`
}

function generateTemplateRuleIds(count: number) {
  const base = `tpl-${Date.now().toString(36)}-${randomBase36Id(4)}`
  return Array.from({ length: count }).map((_, i) => `${base}-${(i + 1).toString(36)}`)
}

function parseExtensions(text: string): string[] {
  return (text || '')
    .split(/[,\s]+/g)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
    .map((s) => (s.startsWith('.') ? s : `.${s}`))
}

type RuleDraft = {
  id: string
  name: string
  enabled: boolean
  extensionsText: string
  filenameRegex: string
  preprocessEnabled: boolean
  preprocessStepIds: string[]
  parserBackend: string
  chunkStrategy: string
  governanceProfileRef: string
  pipelinePatchJson: string
}

function ruleToDraft(rule: IngestionRule): RuleDraft {
  const extensions = Array.isArray(rule.match?.extensions) ? rule.match.extensions : []
  const steps = Array.isArray(rule.preprocess?.steps) ? rule.preprocess.steps : []
  return {
    id: rule.id || safeIdFromNow(),
    name: rule.name || '新规则',
    enabled: !!rule.enabled,
    extensionsText: extensions.join(', '),
    filenameRegex: String(rule.match?.filename_regex || ''),
    preprocessEnabled: !!rule.preprocess?.enabled,
    preprocessStepIds: steps.map((s) => String(s.id || '')).filter(Boolean),
    parserBackend: rule.parser_backend || '',
    chunkStrategy: rule.chunk_strategy || '',
    governanceProfileRef: rule.governance_profile_ref || '',
    pipelinePatchJson: rule.pipeline_patch ? JSON.stringify(rule.pipeline_patch, null, 2) : '',
  }
}

function draftToRule(d: RuleDraft): IngestionRule {
  let patch: Record<string, any> | undefined
  const raw = (d.pipelinePatchJson || '').trim()
  if (raw) {
    patch = JSON.parse(raw)
  }
  return {
    id: d.id.trim(),
    name: d.name.trim(),
    enabled: !!d.enabled,
    match: {
      extensions: parseExtensions(d.extensionsText),
      filename_regex: d.filenameRegex.trim() ? d.filenameRegex.trim() : null,
    },
    preprocess: {
      enabled: !!d.preprocessEnabled,
      steps: d.preprocessEnabled
        ? d.preprocessStepIds.map((id) => ({ id, params: {} }))
        : [],
    },
    parser_backend: d.parserBackend.trim() ? d.parserBackend.trim() : null,
    chunk_strategy: d.chunkStrategy.trim() ? d.chunkStrategy.trim() : null,
    governance_profile_ref: d.governanceProfileRef.trim() ? d.governanceProfileRef.trim() : null,
    pipeline_patch: patch,
  }
}

export default function DatasetIngestionPolicyPage() {
  const router = useRouter()
  const params = useParams<{ id: string }>()
  const datasetId = String(params?.id || '')
  const { capabilities } = usePipelineCapabilities()

  const [policy, setPolicy] = useState<IngestionPolicy | null>(null)
  const [saving, setSaving] = useState(false)

  const [editorOpen, setEditorOpen] = useState(false)
  const [templatesOpen, setTemplatesOpen] = useState(false)
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [rollbackingVersionId, setRollbackingVersionId] = useState<string | null>(null)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [draft, setDraft] = useState<RuleDraft>({
    id: safeIdFromNow(),
    name: '新规则',
    enabled: true,
    extensionsText: '.pdf',
    filenameRegex: '',
    preprocessEnabled: true,
    preprocessStepIds: ['text.reencode_utf8', 'text.strip_bom', 'text.normalize_newlines'],
    parserBackend: 'auto',
    chunkStrategy: '',
    governanceProfileRef: '',
    pipelinePatchJson: '',
  })

  const [previewFile, setPreviewFile] = useState<File | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<IngestionPreviewResponse | null>(null)

  const importInputRef = useRef<HTMLInputElement | null>(null)

  const chunkStrategyOptions = useMemo(() => {
    const items = (capabilities?.chunk_strategies || []).map((s) => String(s.name || '').trim()).filter(Boolean)
    const uniq = Array.from(new Set(items))
    return uniq.length ? uniq : INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES
  }, [capabilities])

  const profilesQuery = useQuery({
    queryKey: queryKeys.governance.profiles(INGESTION_PROFILE_PARAMS),
    queryFn: () => pipelineApi.listGovernanceProfiles(INGESTION_PROFILE_PARAMS),
  })
  const profiles = useMemo(
    () => profilesQuery.data?.items || [],
    [profilesQuery.data?.items]
  )

  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId),
    queryFn: () => datasetApi.get(datasetId),
    enabled: Boolean(datasetId),
  })

  const policyQuery = useQuery({
    queryKey: queryKeys.datasets.ingestionPolicy(datasetId),
    queryFn: () => datasetApi.getIngestionPolicy(datasetId),
    enabled: Boolean(datasetId),
    refetchOnWindowFocus: false,
  })

  const ingestionStatsQuery = useQuery({
    queryKey: queryKeys.datasets.ingestionStats(datasetId),
    queryFn: async () => {
      try {
        return await datasetApi.getIngestionStats(datasetId)
      } catch {
        return null
      }
    },
    enabled: Boolean(datasetId),
  })

  const versionsQuery = useQuery({
    queryKey: queryKeys.datasets.ingestionPolicyVersions(datasetId),
    queryFn: () => {
      if (!datasetId) throw new Error('缺少数据集 ID')
      return datasetApi.listIngestionPolicyVersions(datasetId)
    },
    enabled: false,
  })

  const dataset = datasetQuery.data ?? null
  const ingestionStats = ingestionStatsQuery.data ?? null
  const versions = versionsQuery.data ?? null
  const versionsLoading = versionsQuery.isFetching
  const refreshing = Boolean(datasetId) && (
    datasetQuery.isFetching ||
    policyQuery.isFetching ||
    ingestionStatsQuery.isFetching
  )

  useEffect(() => {
    if (profilesQuery.error) {
      toast.error(formatApiError(profilesQuery.error, '加载治理预设失败'))
    }
  }, [profilesQuery.error])

  useEffect(() => {
    const error = datasetQuery.error || policyQuery.error
    if (!error) return
    console.error('Failed to load dataset ingestion policy', error)
    toast.error(formatApiError(error, '加载入库策略失败'))
  }, [datasetQuery.error, datasetQuery.errorUpdatedAt, policyQuery.error, policyQuery.errorUpdatedAt])

  useEffect(() => {
    setPolicy(policyQuery.data ?? null)
  }, [policyQuery.data])

  const { refetch: refetchDataset } = datasetQuery
  const { refetch: refetchPolicy } = policyQuery
  const { refetch: refetchIngestionStats } = ingestionStatsQuery
  const { refetch: refetchVersions } = versionsQuery

  const refreshIngestionPolicy = useCallback(async () => {
    await Promise.all([
      refetchDataset(),
      refetchPolicy(),
      refetchIngestionStats(),
    ])
  }, [refetchDataset, refetchIngestionStats, refetchPolicy])

  const refreshVersions = useCallback(async () => {
    if (!datasetId) return
    const result = await refetchVersions()
    if (result.error) {
      console.error('Failed to load ingestion policy versions', result.error)
      toast.error(formatApiError(result.error, '加载版本历史失败'))
    }
  }, [datasetId, refetchVersions])

  const openVersions = useCallback(async () => {
    setVersionsOpen(true)
    await refreshVersions()
  }, [refreshVersions])

  const rollbackPolicy = useCallback(
    async (versionId: string) => {
      if (!datasetId) return
      const id = String(versionId || '').trim()
      if (!id) return
      setRollbackingVersionId(id)
      try {
        await datasetApi.rollbackIngestionPolicy(datasetId, { version_id: id })
        toast.success('已回滚入库策略')
        await Promise.all([refreshIngestionPolicy(), refreshVersions()])
      } catch (e: any) {
        console.error('Failed to rollback ingestion policy', e)
        toast.error(formatApiError(e, '回滚失败'))
      } finally {
        setRollbackingVersionId(null)
      }
    },
    [datasetId, refreshIngestionPolicy, refreshVersions]
  )

  const rules = useMemo(() => policy?.rules || [], [policy])

  const openCreate = useCallback(() => {
    setEditingIndex(null)
    setDraft({
      id: safeIdFromNow(),
      name: '新规则',
      enabled: true,
      extensionsText: '.pdf',
      filenameRegex: '',
      preprocessEnabled: true,
      preprocessStepIds: ['text.reencode_utf8', 'text.strip_bom', 'text.normalize_newlines'],
      parserBackend: 'auto',
      chunkStrategy: '',
      governanceProfileRef: '',
      pipelinePatchJson: '',
    })
    setEditorOpen(true)
  }, [])

  const openEdit = useCallback((idx: number) => {
    const r = rules[idx]
    if (!r) return
    setEditingIndex(idx)
    setDraft(ruleToDraft(r))
    setEditorOpen(true)
  }, [rules])

  const applyDraft = useCallback(() => {
    try {
      const rule = draftToRule(draft)
      const next: IngestionPolicy = policy || { version: '1', rules: [] }
      const newRules = [...(next.rules || [])]
      if (editingIndex == null) newRules.unshift(rule)
      else newRules.splice(editingIndex, 1, rule)
      setPolicy({ version: '1', rules: newRules })
      setEditorOpen(false)
    } catch (e: any) {
      toast.error(`规则保存失败：${String(e?.message || e)}`)
    }
  }, [draft, editingIndex, policy])

  const removeRule = useCallback((idx: number) => {
    const next: IngestionPolicy = policy || { version: '1', rules: [] }
    const newRules = [...(next.rules || [])]
    newRules.splice(idx, 1)
    setPolicy({ version: '1', rules: newRules })
  }, [policy])

  const moveRule = useCallback((idx: number, dir: -1 | 1) => {
    const next: IngestionPolicy = policy || { version: '1', rules: [] }
    const newRules = [...(next.rules || [])]
    const j = idx + dir
    if (j < 0 || j >= newRules.length) return
    const tmp = newRules[idx]
    newRules[idx] = newRules[j]
    newRules[j] = tmp
    setPolicy({ version: '1', rules: newRules })
  }, [policy])

  const applyTemplate = useCallback((tpl: IngestionPolicyTemplate, mode: 'prepend' | 'append' | 'replace') => {
    const next: IngestionPolicy = policy || { version: '1', rules: [] }
    const existing = [...(next.rules || [])]
    const ids = generateTemplateRuleIds(tpl.rules.length)
    const newRules: IngestionRule[] = tpl.rules.map((r, i) => ({ ...r, id: ids[i] }))

    const merged =
      (() => {
    if (mode === 'replace') {
        return newRules;
    }
    else if (mode === 'append') {
            return [...existing, ...newRules];
        }
        else {
            return [...newRules, ...existing];
        }
})()

    setPolicy({ version: '1', rules: merged })
    setTemplatesOpen(false)
    toast.success(`已应用模板：${tpl.name}（${newRules.length} 条规则）`)

    // Bring the user back to the top to see the newly inserted rules.
    globalThis.window.requestAnimationFrame(() => {
      const sc = document.querySelector<HTMLElement>('[data-page-scroll-container="true"]')
      sc?.scrollTo({ top: 0, left: 0, behavior: 'smooth' })
    })
  }, [policy])

  const savePolicy = useCallback(async () => {
    if (!datasetId || !policy) return
    setSaving(true)
    try {
      await datasetApi.updateIngestionPolicy(datasetId, policy)
      toast.success('已保存入库策略')
      await refreshIngestionPolicy()
    } catch (e: any) {
      console.error('Failed to save ingestion policy', e)
      toast.error(formatApiError(e, '保存失败（请检查规则ID/扩展名/正则/patch JSON）'))
    } finally {
      setSaving(false)
    }
  }, [datasetId, policy, refreshIngestionPolicy])

  const handleExport = useCallback(async () => {
    if (!datasetId) return
    try {
      const blob = await datasetApi.exportIngestionPolicy(datasetId)
      const safe = (dataset?.name || datasetId).replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.ingestion-policy.json`)
    } catch (e: any) {
      console.error('Failed to export ingestion policy', e)
      toast.error(formatApiError(e, '导出失败'))
    }
  }, [datasetId, dataset])

  const handleImportFile = useCallback(async (file: File | null) => {
    if (!file || !datasetId) return
    try {
      const res = await datasetApi.importIngestionPolicy(datasetId, file, true)
      toast.success(`导入成功：规则 ${res.rule_count}`)
      await refreshIngestionPolicy()
    } catch (e: any) {
      console.error('Failed to import ingestion policy', e)
      toast.error(formatApiError(e, '导入失败（请检查脚本格式/正则是否安全）'))
    } finally {
      if (importInputRef.current) importInputRef.current.value = ''
    }
  }, [datasetId, refreshIngestionPolicy])

  const runPreview = useCallback(async () => {
    if (!previewFile || !datasetId) return
    setPreviewing(true)
    setPreview(null)
    try {
      const res = await pipelineApi.ingestionPreview(previewFile, { dataset_id: datasetId, diff_max_lines: 2000 })
      setPreview(res)
      toast.success('预览已生成')
    } catch (e: any) {
      console.error('Failed to run ingestion preview', e)
      toast.error(formatApiError(e, '预览失败'))
    } finally {
      setPreviewing(false)
    }
  }, [previewFile, datasetId])

  return (
    <AppFrame>
      <PageScaffold
        title="入库策略（解析前预处理）"
        description={
          <span className="text-muted-foreground">
            数据集：<span className="text-foreground font-medium">{dataset?.name || datasetId}</span> · 按文件类型配置“预处理→解析→治理”
          </span>
        }
        icon={Settings2}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => router.push('/datasets')} className="gap-2">
              <ArrowLeft className="w-4 h-4" />
              返回
            </Button>
            <Button variant="outline" onClick={() => detachPromise(refreshIngestionPolicy())} disabled={refreshing} className="gap-2">
              <RefreshCw className={cn('w-4 h-4', refreshing && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            {datasetId ? (
              <Button
                variant="outline"
                onClick={() => router.push(`/datasets/${datasetId}/profile`)}
                className="gap-2"
              >
                <BarChart3 className="w-4 h-4" />
                数据画像
              </Button>
            ) : null}
            {datasetId ? (
              <Button
                variant="outline"
                onClick={() => router.push(`/datasets/${datasetId}/tables`)}
                className="gap-2"
              >
                <Table2 className="w-4 h-4" />
                表格 / TAG
              </Button>
            ) : null}
	            <Button variant="outline" onClick={handleExport} className="gap-2">
	              <Download className="w-4 h-4" />
	              导出脚本
	            </Button>
	            <Button variant="outline" onClick={() => importInputRef.current?.click()} className="gap-2">
	              <FileUp className="w-4 h-4" />
	              导入脚本
	            </Button>
              <Button variant="outline" onClick={() => detachPromise(openVersions())} className="gap-2">
                <History className="w-4 h-4" />
                版本
              </Button>
	            <Button onClick={savePolicy} disabled={saving || !policy} className="gap-2">
	              {saving ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Save className="w-4 h-4" />}
	              保存
	            </Button>
	          </div>
	        }
      >
        <div className="space-y-6">
          {ingestionStats ? (
            <StatsGrid className="mt-2">
              <StatCard
                icon={FileUp}
                label="文档数"
                value={ingestionStats.total_documents}
                subValue={`completed ${(ingestionStats.by_status?.completed || 0)} · failed ${(ingestionStats.by_status?.failed || 0)}`}
                color="sky"
              />
              <StatCard
                icon={Scissors}
                label="切片数"
                value={ingestionStats.total_chunks}
                subValue="sum(chunk_count)"
                color="teal"
              />
              <StatCard
                icon={BarChart3}
                label="总字符数"
                value={ingestionStats.total_characters}
                subValue="sum(total_characters)"
                color="amber"
              />
              <StatCard
                icon={RefreshCw}
                label="最近入库"
                value={ingestionStats.last_processed_at ? new Date(ingestionStats.last_processed_at).toLocaleString() : '—'}
                subValue="processed_at"
                color="green"
              />
            </StatsGrid>
          ) : null}

          <Panel variant="glass" className="overflow-hidden">
            <div className="px-5 py-4 border-b border-border/60 flex items-center justify-between">
              <div className="min-w-0">
                <div className="text-sm font-semibold">规则列表</div>
                <div className="text-xs text-muted-foreground mt-1">
                  从上到下匹配，命中后应用：预处理步骤 / 解析后端 / chunk 策略 / 治理预设 / pipeline_patch
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" onClick={() => setTemplatesOpen(true)} className="gap-2">
                  <Sparkles className="w-4 h-4" />
                  从模板添加
                </Button>
                <Button onClick={openCreate} className="gap-2">
                  <Plus className="w-4 h-4" />
                  新增规则
                </Button>
              </div>
            </div>

            <div className="divide-y divide-border/60">
              {(rules || []).length === 0 ? (
                <div className="p-6 text-sm text-muted-foreground">
                  暂无规则。建议先添加：PDF / HTML / 纯文本 三条规则，分别选择治理预设并开启“文本编码修复”。
                </div>
              ) : (
                (rules || []).map((r, idx) => (
                  <div key={r.id} className="p-5 flex items-start justify-between gap-6 hover:bg-muted/20 transition-colors">
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold truncate">{r.name}</span>
                            <Badge variant={r.enabled ? 'soft' : 'outline'} className="text-[11px] font-mono uppercase ">
                              {r.enabled ? 'enabled' : 'disabled'}
                            </Badge>
                            <span className="text-xs text-muted-foreground font-mono">#{idx + 1}</span>
                          </div>
                          <div className="text-xs text-muted-foreground mt-1">
                            ext: {(r.match?.extensions || []).join(', ') || '（任意）'}
                            {r.match?.filename_regex ? ` · filename_regex: ${r.match.filename_regex}` : ''}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          <Button variant="outline" size="sm" onClick={() => moveRule(idx, -1)} disabled={idx === 0}>
                            ↑
                          </Button>
                          <Button variant="outline" size="sm" onClick={() => moveRule(idx, 1)} disabled={idx === rules.length - 1}>
                            ↓
                          </Button>
                          <Button variant="outline" size="sm" onClick={() => openEdit(idx)}>
                            编辑
                          </Button>
                          <Button variant="destructive" size="sm" className="gap-2" onClick={() => removeRule(idx)}>
                            <Trash2 className="w-4 h-4" />
                            删除
                          </Button>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <Badge variant="outline" className="font-mono">
                          preprocess: {r.preprocess?.enabled ? (r.preprocess?.steps || []).length : 0}
                        </Badge>
                        {r.parser_backend ? <Badge variant="outline" className="font-mono">parser: {r.parser_backend}</Badge> : null}
                        {r.chunk_strategy ? <Badge variant="outline" className="font-mono">chunk: {r.chunk_strategy}</Badge> : null}
                        {r.governance_profile_ref ? <Badge variant="outline" className="font-mono">profile: {r.governance_profile_ref}</Badge> : null}
                        {r.pipeline_patch && Object.keys(r.pipeline_patch || {}).length > 0 ? (
                          <Badge variant="outline" className="font-mono">patch: {Object.keys(r.pipeline_patch || {}).length}</Badge>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Panel>

          <Panel variant="glass" className="overflow-hidden">
            <div className="px-5 py-4 border-b border-border/60 flex items-center justify-between">
              <div className="min-w-0">
                <div className="text-sm font-semibold flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-primary" />
                  入库预览（样例文件）
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  上传一个样例文件，后端会按当前数据集策略执行：匹配规则 → 预处理 → 解析 → 治理 diff/问题。
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Input
                  type="file"
                  className="max-w-[260px]"
                  onChange={(e) => setPreviewFile(e.target.files?.[0] || null)}
                />
                <Button onClick={runPreview} disabled={!previewFile || previewing} className="gap-2">
                  {previewing ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Sparkles className="w-4 h-4" />}
                  生成预览
                </Button>
              </div>
            </div>

            {preview ? (
              <div className="p-5 space-y-4">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge variant={preview.rule?.matched ? 'soft' : 'outline'} className="font-mono">
                    matched: {preview.rule?.matched ? 'true' : 'false'}
                  </Badge>
                  {preview.rule?.rule_name ? <Badge variant="outline" className="font-mono">{preview.rule.rule_name}</Badge> : null}
                  <Badge variant="outline" className="font-mono">parser: {preview.rule?.parser_backend}</Badge>
                  {preview.rule?.chunk_strategy ? <Badge variant="outline" className="font-mono">chunk: {preview.rule.chunk_strategy}</Badge> : null}
                  {preview.rule?.governance_profile_ref ? <Badge variant="outline" className="font-mono">profile: {preview.rule.governance_profile_ref}</Badge> : null}
                  <Badge variant="outline" className="font-mono">preprocess_changed: {String(preview.preprocess?.changed)}</Badge>
                </div>

                {Array.isArray(preview.clean?.issues) && preview.clean.issues.length > 0 ? (
                  <Panel variant="muted" className="p-4">
                    <div className="text-sm font-semibold mb-2">后端检测到的问题（issues）</div>
                    <div className="space-y-2">
                      {preview.clean.issues.slice(0, 8).map((it) => (
                        <div key={`${it.code}-${it.message}`} className="text-xs">
                          <span className="font-mono text-muted-foreground">{it.severity}</span>{' '}
                          <span className="font-mono">{it.code}</span> · {it.message}
                          {it.count ? <span className="text-muted-foreground"> ×{it.count}</span> : null}
                        </div>
                      ))}
                      {preview.clean.issues.length > 8 ? (
                        <div className="text-xs text-muted-foreground">… 还有 {preview.clean.issues.length - 8} 条</div>
                      ) : null}
                    </div>
                  </Panel>
                ) : null}

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <Panel variant="muted" className="p-0 overflow-hidden">
                    <div className="px-4 py-3 border-b border-border/60 text-sm font-semibold">解析后 Markdown（raw）</div>
                    <pre className="p-4 text-xs leading-relaxed whitespace-pre-wrap overflow-y-auto max-h-[360px] no-scrollbar">
                      {preview.parse?.markdown || ''}
                    </pre>
                  </Panel>
                  <Panel variant="muted" className="p-0 overflow-hidden">
                    <div className="px-4 py-3 border-b border-border/60 text-sm font-semibold">治理后 Markdown（clean）</div>
                    <pre className="p-4 text-xs leading-relaxed whitespace-pre-wrap overflow-y-auto max-h-[360px] no-scrollbar">
                      {preview.clean?.markdown || ''}
                    </pre>
                  </Panel>
                </div>

                {preview.clean?.diff_unified ? (
                  <Panel variant="muted" className="p-0 overflow-hidden">
                    <div className="px-4 py-3 border-b border-border/60 text-sm font-semibold">Unified Diff（后端）</div>
                    <pre className="p-4 text-xs leading-relaxed whitespace-pre overflow-y-auto max-h-[320px] no-scrollbar font-mono">
                      {preview.clean.diff_unified}
                    </pre>
                  </Panel>
                ) : null}
              </div>
            ) : (
              <div className="p-6 text-sm text-muted-foreground">
                选择一个样例文件后点击“生成预览”。建议：网页 HTML、PDF、以及带表格的 DOCX/CSV 各试一次。
              </div>
            )}
          </Panel>
        </div>

        <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
          <DialogContent className="max-w-3xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-xl font-bold text-foreground">{editingIndex == null ? '新增规则' : '编辑规则'}</DialogTitle>
              <DialogDescription className="text-muted-foreground">
                提示：规则从上到下匹配。扩展名支持 .pdf / pdf 两种写法；filename_regex 为可选。
              </DialogDescription>
            </DialogHeader>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>规则 ID（唯一）</Label>
                  <Input value={draft.id} onChange={(e) => setDraft({ ...draft, id: e.target.value })} />
                </div>
                <div className="space-y-2">
                  <Label>规则名称</Label>
                  <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                </div>
                <div className="flex items-center justify-between rounded-xl border border-border/60 p-3">
                  <div>
                    <div className="text-sm font-semibold">启用规则</div>
                    <div className="text-xs text-muted-foreground">禁用后不会被匹配</div>
                  </div>
                  <Switch checked={draft.enabled} onCheckedChange={(v) => setDraft({ ...draft, enabled: v })} />
                </div>
                <div className="space-y-2">
                  <Label>匹配扩展名（逗号分隔，空=任意）</Label>
                  <Input
                    value={draft.extensionsText}
                    onChange={(e) => setDraft({ ...draft, extensionsText: e.target.value })}
                    placeholder=".pdf, .docx, .html"
                  />
                </div>
                <div className="space-y-2">
                  <Label>filename_regex（可选）</Label>
                  <Input
                    value={draft.filenameRegex}
                    onChange={(e) => setDraft({ ...draft, filenameRegex: e.target.value })}
                    placeholder="例如：(?i)invoice|发票"
                  />
                </div>

                <Panel variant="muted" className="p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-semibold">解析前预处理</div>
                      <div className="text-xs text-muted-foreground">在解析前对原始文件做修复/清洗</div>
                    </div>
                    <Switch checked={draft.preprocessEnabled} onCheckedChange={(v) => setDraft({ ...draft, preprocessEnabled: v })} />
                  </div>
                  <div className={cn('mt-3 space-y-2', !draft.preprocessEnabled && 'opacity-50 pointer-events-none')}>
                    {PREPROCESS_STEP_CATALOG.map((s) => {
                      const checked = draft.preprocessStepIds.includes(s.id)
                      return (
                        <div key={s.id} className="flex items-start gap-3 rounded-lg border border-border/60 p-3 hover:bg-muted/30 transition-colors cursor-pointer">
                          <Checkbox
                            checked={checked}
                            onCheckedChange={(v) => {
                              const next = new Set(draft.preprocessStepIds)
                              if (v) next.add(s.id)
                              else next.delete(s.id)
                              setDraft({ ...draft, preprocessStepIds: Array.from(next) })
                            }}
                          />
                          <div className="min-w-0">
                            <div className="text-sm font-medium">{s.label}</div>
                            <div className="text-xs text-muted-foreground">{s.desc}</div>
                            <div className="text-[11px] text-muted-foreground font-mono mt-1">{s.id}</div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </Panel>
              </div>

              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>解析后端（可选覆盖）</Label>
                  <Select value={draft.parserBackend || NONE} onValueChange={(v) => setDraft({ ...draft, parserBackend: v === NONE ? '' : v })}>
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="不覆盖（使用默认/手动选择）" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>不覆盖</SelectItem>
                      {PARSER_BACKEND_REGISTRY_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <div className="text-xs text-muted-foreground">
                    建议：PDF 默认 auto；网页/Office 可选 pandoc 或 markitdown（按你环境可用性）。
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>Chunk 策略（可选覆盖）</Label>
                  <Select value={draft.chunkStrategy || NONE} onValueChange={(v) => setDraft({ ...draft, chunkStrategy: v === NONE ? '' : v })}>
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="不覆盖" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>不覆盖</SelectItem>
                      {chunkStrategyOptions.map((name) => (
                        <SelectItem key={name} value={name}>
                          {name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>治理预设（Profiles/脚本，可选）</Label>
                  <Select value={draft.governanceProfileRef || NONE} onValueChange={(v) => setDraft({ ...draft, governanceProfileRef: v === NONE ? '' : v })}>
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="不使用预设" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={NONE}>不使用预设</SelectItem>
                      {profiles.map((p) => (
                        <SelectItem key={p.key || p.id || p.name} value={p.key || p.id || p.name}>
                          {p.is_system ? '内置' : '自定义'} · {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <div className="text-xs text-muted-foreground">
                    预设会注入 pipeline_patch + regex_rules（后端同样做安全校验）。
                  </div>
                </div>

                <div className="space-y-2">
                  <Label>高级：pipeline_patch（JSON，可选）</Label>
	                  <Textarea
	                    value={draft.pipelinePatchJson}
	                    onChange={(e) => setDraft({ ...draft, pipelinePatchJson: e.target.value })}
	                    placeholder={`{\n  "governance_enabled": true,\n  "governance_remove_boilerplate": true\n}`}
	                    className="min-h-[220px] font-mono text-xs"
	                  />
                  <div className="text-xs text-muted-foreground">
                    仅允许 DocumentPipelineOptions 的字段；未知字段会被后端拒绝。
                  </div>
                </div>
              </div>
            </div>

            <DialogFooter className="mt-4">
              <Button variant="ghost" onClick={() => setEditorOpen(false)}>取消</Button>
              <Button onClick={applyDraft}>保存规则</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog open={templatesOpen} onOpenChange={setTemplatesOpen}>
          <DialogContent className="max-w-3xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-primary" />
                入库策略模板
              </DialogTitle>
              <DialogDescription>
                一键生成常用规则组合（可追加/替换）。注意：规则按从上到下命中，必要时请调整顺序。
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3">
              {INGESTION_POLICY_TEMPLATES.map((tpl) => (
                <div key={tpl.key} className="rounded-xl border border-border/60 p-4 hover:bg-muted/20 transition-colors">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="font-semibold">{tpl.name}</div>
                      <div className="text-xs text-muted-foreground mt-1">{tpl.description}</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {tpl.tags.map((t) => (
                          <Badge key={t} variant="outline" className="text-[11px] font-mono">
                            {t}
                          </Badge>
                        ))}
                        <Badge variant="soft" className="text-[11px] font-mono">
                          rules: {tpl.rules.length}
                        </Badge>
                      </div>
                    </div>
                    <div className="flex flex-col gap-2 flex-shrink-0">
                      <Button size="sm" onClick={() => applyTemplate(tpl, 'prepend')}>
                        追加到顶部
                      </Button>
                      <Button size="sm" variant="outline" onClick={() => applyTemplate(tpl, 'append')}>
                        追加到底部
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => applyTemplate(tpl, 'replace')}>
                        替换当前策略
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <DialogFooter className="mt-2">
              <Button variant="ghost" onClick={() => setTemplatesOpen(false)}>
                关闭
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Dialog open={versionsOpen} onOpenChange={setVersionsOpen}>
          <DialogContent className="max-w-3xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <History className="w-4 h-4 text-primary" />
                入库策略版本历史
              </DialogTitle>
              <DialogDescription>
                每次“保存/导入/回滚”都会生成一个版本（保留最近 {50} 条）。可用来快速回退错误配置。
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] text-muted-foreground">
                  current_version_id:{' '}
                  <span className="font-mono">{versions?.current_version_id ? String(versions.current_version_id) : '—'}</span>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-8 px-3 text-[11px] gap-2"
                  onClick={() => detachPromise(refreshVersions())}
                  disabled={versionsLoading}
                >
                  <RefreshCw className={cn('w-4 h-4', versionsLoading && 'animate-spin motion-reduce:animate-none')} />
                  刷新
                </Button>
              </div>

              <div className="max-h-[520px] overflow-auto pr-2 space-y-2">
                {(() => {
    if (versionsLoading) {
        return (<div className="text-sm text-muted-foreground">加载中…</div>);
    }
    else if ((versions?.items || []).length) {
            return ((versions?.items || []).map((v, idx) => {
                const id = String(v?.id || '').trim();
                const isCurrent = Boolean(id && versions?.current_version_id && id === versions.current_version_id);
                const createdAt = String(v?.created_at || '').trim();
                const source = String(v?.source || '').trim() || 'put';
                const createdBy = String(v?.created_by || '').trim();
                const policyJson = v?.policy;
                return (<div key={id || String(idx)} className="rounded-xl border border-border/60 bg-card p-3">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-[12px]">{id || '—'}</span>
                              {isCurrent ? <Badge variant="soft">current</Badge> : null}
                              <Badge variant="outline" className="font-mono">
                                {source}
                              </Badge>
                            </div>
                            <div className="mt-1 text-[11px] text-muted-foreground">
                              {createdAt ? new Date(createdAt).toLocaleString() : '—'}
                              {createdBy ? <span className="ml-2 font-mono">by {createdBy}</span> : null}
                            </div>
                          </div>

                          <Button type="button" size="sm" variant={isCurrent ? 'secondary' : 'destructive'} className="h-8 px-3 text-[11px]" onClick={() => detachPromise(rollbackPolicy(id))} disabled={!id || isCurrent || Boolean(rollbackingVersionId)}>
                            {rollbackingVersionId === id ? (<Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none"/>) : null}
                            回滚
                          </Button>
                        </div>

                        <details className="mt-2">
                          <summary className="cursor-pointer select-none text-[11px] text-muted-foreground hover:text-foreground">
                            查看 policy
                          </summary>
                          <pre className="mt-2 max-h-[220px] overflow-auto rounded-lg border border-border/60 bg-muted/30 p-2 text-[11px] text-muted-foreground">
                            {JSON.stringify(policyJson ?? null, null, 2)}
                          </pre>
                        </details>
                      </div>);
            }));
        }
        else {
            return (<div className="text-sm text-muted-foreground">暂无版本（保存/导入后会自动生成）</div>);
        }
})()}
              </div>
            </div>

            <DialogFooter className="mt-2">
              <Button variant="ghost" onClick={() => setVersionsOpen(false)}>
                关闭
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <input
          ref={importInputRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => handleImportFile(e.target.files?.[0] || null)}
        />
      </PageScaffold>
    </AppFrame>
  )
}
