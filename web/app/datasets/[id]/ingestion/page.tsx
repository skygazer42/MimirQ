'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, BarChart3, Cloud, Database, FileSearch, FileUp, Heart, Loader2, Plus, RefreshCw, Save, Scissors, Settings2, ShieldCheck, Sparkles, Table2, Trash2 } from 'lucide-react'

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

import { datasetApi, pipelineApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { INGESTION_FALLBACK_CHUNK_STRATEGY_VALUES } from '@/lib/chunk-strategies'
import { reportClientError } from '@/lib/client-logging'
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
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
  let patch: Record<string, unknown> | undefined
  const raw = (d.pipelinePatchJson || '').trim()
  if (raw) {
    const parsed: unknown = JSON.parse(raw)
    if (!isRecord(parsed)) {
      throw new Error('pipeline patch must be a JSON object')
    }
    patch = parsed
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

  const dataset = datasetQuery.data ?? null
  const ingestionStats = ingestionStatsQuery.data ?? null

  useEffect(() => {
    if (profilesQuery.error) {
      toast.error(formatApiError(profilesQuery.error, '加载治理预设失败'))
    }
  }, [profilesQuery.error])

  useEffect(() => {
    const error = datasetQuery.error || policyQuery.error
    if (!error) return
    reportClientError('Failed to load dataset ingestion policy', error)
    toast.error(formatApiError(error, '加载入库策略失败'))
  }, [datasetQuery.error, datasetQuery.errorUpdatedAt, policyQuery.error, policyQuery.errorUpdatedAt])

  useEffect(() => {
    setPolicy(policyQuery.data ?? null)
  }, [policyQuery.data])

  const { refetch: refetchDataset } = datasetQuery
  const { refetch: refetchPolicy } = policyQuery
  const { refetch: refetchIngestionStats } = ingestionStatsQuery

  const refreshIngestionPolicy = useCallback(async () => {
    await Promise.all([
      refetchDataset(),
      refetchPolicy(),
      refetchIngestionStats(),
    ])
  }, [refetchDataset, refetchIngestionStats, refetchPolicy])

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
    } catch (e: unknown) {
      toast.error(`规则保存失败：${errorMessage(e)}`)
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
    } catch (e: unknown) {
      reportClientError('Failed to save ingestion policy', e)
      toast.error(formatApiError(e, '保存失败（请检查规则ID/扩展名/正则/patch JSON）'))
    } finally {
      setSaving(false)
    }
  }, [datasetId, policy, refreshIngestionPolicy])

  const runPreview = useCallback(async () => {
    if (!previewFile || !datasetId) return
    setPreviewing(true)
    setPreview(null)
    try {
      const res = await pipelineApi.ingestionPreview(previewFile, { dataset_id: datasetId, diff_max_lines: 2000 })
      setPreview(res)
      toast.success('预览已生成')
    } catch (e: unknown) {
      reportClientError('Failed to run ingestion preview', e)
      toast.error(formatApiError(e, '预览失败'))
    } finally {
      setPreviewing(false)
    }
  }, [previewFile, datasetId])

  const ingestionHeroCard = 'relative overflow-hidden rounded-[26px] border border-slate-200/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.98),rgba(246,248,251,0.94)_45%,rgba(232,246,250,0.72))] shadow-[0_24px_70px_rgba(15,23,42,0.10)] ring-1 ring-white/80 before:pointer-events-none before:absolute before:inset-0 before:bg-[radial-gradient(circle_at_16%_10%,rgba(8,145,178,0.16),transparent_26%),radial-gradient(circle_at_82%_0%,rgba(15,23,42,0.075),transparent_24%),linear-gradient(90deg,rgba(15,23,42,0.035)_1px,transparent_1px)] before:bg-[length:auto,auto,34px_34px] dark:border-border/60 dark:bg-card/95 dark:ring-white/5'
  const ingestionToolbarGroupClass = 'inline-flex flex-wrap items-center gap-1 rounded-2xl border border-slate-200/80 bg-white/82 p-1 shadow-[0_12px_34px_rgba(15,23,42,0.07)] ring-1 ring-white/75 backdrop-blur dark:border-border/60 dark:bg-card/70 dark:ring-white/5'
  const ingestionToolbarButtonClass = 'h-8 gap-1.5 rounded-xl px-2.5 text-[12px] font-semibold text-slate-600 shadow-none hover:bg-white hover:text-slate-950 hover:shadow-sm dark:text-muted-foreground dark:hover:bg-muted/60 dark:hover:text-foreground [&_svg]:size-3.5'
  const ingestionToolbarPrimaryButtonClass = 'h-8 min-w-[104px] gap-1.5 rounded-xl bg-slate-950 px-3.5 text-[12px] font-semibold text-white shadow-[0_12px_26px_rgba(15,23,42,0.22)] hover:bg-slate-800 dark:bg-primary dark:text-primary-foreground dark:hover:bg-primary/90 [&_svg]:size-3.5'
  const ingestionPanelClass = 'rounded-[24px] border-slate-200/80 bg-white/88 shadow-[0_18px_54px_rgba(15,23,42,0.08)] ring-1 ring-white/75 backdrop-blur-xl dark:border-border/60 dark:bg-card/82 dark:ring-white/5'
  const ingestionPanelHeaderClass = 'shrink-0 border-b border-slate-200/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.94),rgba(248,250,252,0.78))] px-5 py-4 dark:border-border/60 dark:bg-muted/20'
  const ingestionIconPillClass = 'flex size-9 shrink-0 items-center justify-center rounded-2xl border border-slate-200/80 bg-white text-slate-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.85),0_8px_22px_rgba(15,23,42,0.08)] dark:border-border/60 dark:bg-muted/30 dark:text-foreground'
  const ingestionActionButtonClass = 'h-9 rounded-xl px-3 text-[12px] font-semibold shadow-sm [&_svg]:size-4'
  const ingestionMetricCardClass = 'group relative overflow-hidden rounded-2xl border border-slate-200/80 bg-white/90 px-4 py-3 shadow-[0_12px_32px_rgba(15,23,42,0.055)] ring-1 ring-white/80 transition-colors hover:border-slate-300 dark:border-border/60 dark:bg-card/80 dark:ring-white/5'
  const activeRuleCount = rules.filter((rule) => rule.enabled !== false).length
  const parserBackendCount = new Set(rules.map((rule) => rule.parser_backend).filter(Boolean)).size

  return (
    <AppFrame>
      <PageScaffold
        title="入库策略"
        showHeader={false}
        size="full"
        density="system-dense"
        bodyGutter="dense"
        bodyClassName="h-full overflow-hidden bg-[radial-gradient(circle_at_16%_0%,rgba(8,145,178,0.12),transparent_30%),radial-gradient(circle_at_84%_10%,rgba(15,23,42,0.055),transparent_28%),linear-gradient(180deg,rgba(248,250,252,0.98),rgba(239,244,248,0.76))] pb-3 dark:bg-[radial-gradient(circle_at_18%_0%,rgba(14,165,233,0.14),transparent_28%),linear-gradient(180deg,rgba(15,23,42,0.96),rgba(15,23,42,0.86))]"
        bodyContainerClassName="h-full min-h-0 overflow-hidden"
        top={
          <div className={ingestionHeroCard}>
            <div className="absolute inset-y-4 left-3 w-1 rounded-full bg-gradient-to-b from-primary via-sky-400 to-cyan-300" />
            <div className="relative flex flex-col gap-3 px-5 py-3.5 pl-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-w-0 items-start gap-3.5">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl border border-sky-200/80 bg-white/82 text-primary shadow-[inset_0_1px_0_rgba(255,255,255,0.9),0_10px_26px_rgba(14,165,233,0.14)] dark:border-sky-500/25 dark:bg-sky-500/10">
                  <Settings2 className="size-5" />
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h1 className="truncate text-[22px] font-semibold leading-none tracking-[-0.035em] text-slate-950 dark:text-foreground">入库策略工作台</h1>
                    <span className="inline-flex h-5 items-center rounded-full border border-slate-300/70 bg-white/82 px-2 text-[10px] font-bold uppercase leading-none tracking-[0.12em] text-slate-500 shadow-[inset_0_1px_0_rgba(255,255,255,0.75)] dark:border-border/60 dark:bg-muted/30 dark:text-muted-foreground">
                      pipeline policy
                    </span>
                    <Badge variant="soft" className="h-5 border-primary/20 bg-primary/10 px-2 font-mono text-[10px] leading-none text-primary">
                      POLICY
                    </Badge>
                  </div>
                  <div className="mt-1.5 text-[13px] leading-tight text-slate-600 dark:text-muted-foreground">
                    <span className="font-semibold text-foreground">数据集：</span>
                    <span className="font-medium text-foreground">{dataset?.name || datasetId}</span>
                    <span> · 按文件类型配置预处理、解析、治理与切块入口</span>
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px] font-medium leading-none text-slate-500 dark:text-muted-foreground">
                    <span className="inline-flex items-center gap-1.5">
                      <Database className="size-3.5 text-muted-foreground/80" />
                      <span>规则</span>
                      <span className="font-mono font-semibold text-foreground">{rules.length}</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <ShieldCheck className="size-3.5 text-muted-foreground/80" />
                      <span>启用</span>
                      <span className="font-mono font-semibold text-foreground">{activeRuleCount}</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <Cloud className="size-3.5 text-muted-foreground/80" />
                      <span>解析后端</span>
                      <span className="font-mono font-semibold text-foreground">{parserBackendCount || '--'}</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <FileSearch className="size-3.5 text-muted-foreground/80" />
                      <span>预览</span>
                      <span className="font-semibold text-foreground">样例文件链路验证</span>
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 flex-col items-stretch gap-2 lg:w-[360px]">
                <div className="grid grid-cols-3 gap-2">
                  {[
                    ['01', '匹配规则'],
                    ['02', '解析治理'],
                    ['03', '切块入库'],
                  ].map(([step, label]) => (
                    <div key={step} className="rounded-2xl border border-white/75 bg-white/72 px-3 py-2 shadow-[0_10px_26px_rgba(15,23,42,0.07)] ring-1 ring-slate-200/40 backdrop-blur">
                      <div className="font-mono text-[10px] font-black leading-none text-sky-600">{step}</div>
                      <div className="mt-1 truncate text-[11px] font-bold leading-none text-slate-800">{label}</div>
                    </div>
                  ))}
                </div>
                <div className="inline-flex h-9 items-center gap-2 rounded-xl border border-emerald-200/80 bg-emerald-50/95 px-3 text-[12px] font-semibold text-emerald-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.75),0_10px_24px_rgba(5,150,105,0.10)] dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                  <span className="size-2 rounded-full bg-emerald-500" />
                  策略可编辑
                </div>
              </div>
            </div>
          </div>
        }
        toolbar={
          <div className="flex w-full flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <div className={ingestionToolbarGroupClass}>
              <Button size="sm" variant="ghost" onClick={() => router.push('/datasets')} className={ingestionToolbarButtonClass}>
                <ArrowLeft className="size-3.5" />
                返回
              </Button>
              {datasetId ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => router.push(`/datasets/${datasetId}/health`)}
                  className={ingestionToolbarButtonClass}
                >
                  <Heart className="size-3.5" />
                  健康
                </Button>
              ) : null}
              {datasetId ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => router.push(`/datasets/${datasetId}/precheck`)}
                  className={ingestionToolbarButtonClass}
                >
                  <ShieldCheck className="size-3.5" />
                  预检
                </Button>
              ) : null}
              {datasetId ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => router.push(`/datasets/${datasetId}/profile`)}
                  className={ingestionToolbarButtonClass}
                >
                  <BarChart3 className="size-3.5" />
                  数据画像
                </Button>
              ) : null}
              {datasetId ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => router.push(`/datasets/${datasetId}/tables`)}
                  className={ingestionToolbarButtonClass}
                >
                  <Table2 className="size-3.5" />
                  表格 / TAG
                </Button>
              ) : null}
            </div>
            <Button size="sm" onClick={savePolicy} disabled={saving || !policy} className={ingestionToolbarPrimaryButtonClass}>
              {saving ? <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" /> : <Save className="size-3.5" />}
              保存
            </Button>
          </div>
        }
      >
        <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
          {ingestionStats ? (
            <div className="grid shrink-0 grid-cols-2 gap-3 md:grid-cols-4">
              {[
                {
                  icon: FileUp,
                  label: '文档数',
                  value: ingestionStats.total_documents,
                  subValue: `completed ${(ingestionStats.by_status?.completed || 0)} · failed ${(ingestionStats.by_status?.failed || 0)}`,
                  tone: 'text-sky-600 bg-sky-50 border-sky-100',
                },
                {
                  icon: Scissors,
                  label: '切片数',
                  value: ingestionStats.total_chunks,
                  subValue: 'sum(chunk_count)',
                  tone: 'text-teal-600 bg-teal-50 border-teal-100',
                },
                {
                  icon: BarChart3,
                  label: '总字符数',
                  value: ingestionStats.total_characters,
                  subValue: 'sum(total_characters)',
                  tone: 'text-amber-700 bg-amber-50 border-amber-100',
                },
                {
                  icon: RefreshCw,
                  label: '最近入库',
                  value: ingestionStats.last_processed_at ? new Date(ingestionStats.last_processed_at).toLocaleString() : '—',
                  subValue: 'processed_at',
                  tone: 'text-emerald-700 bg-emerald-50 border-emerald-100',
                },
              ].map((item) => (
                <div key={item.label} className={ingestionMetricCardClass}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400 dark:text-muted-foreground">{item.label}</div>
                      <div className="mt-1 truncate font-mono text-[17px] font-black leading-none tracking-[-0.02em] text-slate-950 tabular-nums dark:text-foreground">
                        {item.value}
                      </div>
                      <div className="mt-1.5 truncate text-[11px] font-medium text-slate-500 dark:text-muted-foreground">{item.subValue}</div>
                    </div>
                    <div className={cn('flex size-8 shrink-0 items-center justify-center rounded-xl border', item.tone)}>
                      <item.icon className="size-4" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : null}

          <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 xl:grid-cols-[minmax(0,1fr)_440px]">
          <Panel variant="glass" className={cn(ingestionPanelClass, 'flex min-h-0 flex-col overflow-hidden')}>
            <div className={cn(ingestionPanelHeaderClass, 'flex items-center justify-between gap-4')}>
              <div className="flex min-w-0 items-start gap-3">
                <div className={ingestionIconPillClass}>
                  <Settings2 className="size-4" />
                </div>
                <div className="min-w-0">
                  <div className="mb-1 font-mono text-[10px] font-black uppercase tracking-[0.18em] text-sky-600">Policy routing</div>
                  <div className="flex items-center gap-2">
                    <div className="text-[15px] font-bold tracking-[-0.015em] text-slate-950 dark:text-foreground">规则列表</div>
                    <Badge variant="outline" className="h-5 rounded-full px-2 font-mono text-[10px] uppercase text-slate-500">
                      {rules.length} rules
                    </Badge>
                  </div>
                  <div className="mt-1 max-w-3xl text-[12px] leading-5 text-slate-500 dark:text-muted-foreground">
                    从上到下匹配，命中后应用：预处理步骤 / 解析后端 / chunk 策略 / 治理预设 / pipeline_patch
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <Button variant="outline" onClick={() => setTemplatesOpen(true)} className={cn(ingestionActionButtonClass, 'border-slate-200 bg-white/90 hover:bg-slate-50')}>
                  <Sparkles className="size-4" />
                  从模板添加
                </Button>
                <Button onClick={openCreate} className={cn(ingestionActionButtonClass, 'bg-sky-600 text-white shadow-[0_12px_24px_rgba(2,132,199,0.24)] hover:bg-sky-700')}>
                  <Plus className="size-4" />
                  新增规则
                </Button>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto bg-[linear-gradient(180deg,rgba(248,250,252,0.72),rgba(255,255,255,0.92))] p-4 no-scrollbar dark:bg-muted/5">
              {(rules || []).length === 0 ? (
                <div className="flex min-h-[260px] flex-col justify-center rounded-[22px] border border-dashed border-slate-300 bg-white/72 px-6 py-8 text-slate-500 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)] dark:border-border dark:bg-muted/20 dark:text-muted-foreground">
                  <div className="flex items-start gap-4">
                    <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-slate-100 text-slate-500 dark:bg-muted/40">
                      <Sparkles className="size-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[15px] font-bold tracking-[-0.01em] text-slate-900 dark:text-foreground">还没有入库规则</div>
                      <div className="mt-1 max-w-xl text-[12px] leading-6">
                        建议先从模板生成 PDF / HTML / 纯文本规则，再按数据集情况调整解析后端、治理预设和 chunk 策略。
                      </div>
                      <div className="mt-4 flex flex-wrap gap-2">
                        <Button variant="outline" size="sm" className="rounded-xl bg-white text-[12px] font-semibold" onClick={() => setTemplatesOpen(true)}>
                          <Sparkles className="size-3.5" />
                          从模板开始
                        </Button>
                        <Button size="sm" className="rounded-xl bg-slate-950 text-[12px] font-semibold text-white hover:bg-slate-800" onClick={openCreate}>
                          <Plus className="size-3.5" />
                          手动新增
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                (rules || []).map((r, idx) => (
                  <div key={r.id} className="group relative mb-3 overflow-hidden rounded-[22px] border border-slate-200/80 bg-white/96 p-4 pl-5 shadow-[0_16px_38px_rgba(15,23,42,0.07)] ring-1 ring-white/85 transition-colors last:mb-0 hover:border-sky-200 dark:border-border/60 dark:bg-card/72 dark:ring-white/5">
                    <div className="absolute inset-y-4 left-0 w-1 rounded-r-full bg-gradient-to-b from-sky-500 via-cyan-400 to-emerald-400 opacity-85" />
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-[15px] font-bold tracking-[-0.01em] text-slate-950 dark:text-foreground">{r.name}</span>
                            <Badge variant={r.enabled ? 'soft' : 'outline'} className="h-5 rounded-full px-2 text-[10px] font-mono uppercase">
                              {r.enabled ? 'enabled' : 'disabled'}
                            </Badge>
                            <span className="rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] font-semibold text-slate-500 dark:bg-muted/50 dark:text-muted-foreground">#{idx + 1}</span>
                          </div>
                          <div className="mt-1.5 text-[12px] font-medium text-slate-500 dark:text-muted-foreground">
                            ext: {(r.match?.extensions || []).join(', ') || '（任意）'}
                            {r.match?.filename_regex ? ` · filename_regex: ${r.match.filename_regex}` : ''}
                          </div>
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          <Button variant="outline" size="sm" className="size-8 rounded-xl px-0 text-[12px]" onClick={() => moveRule(idx, -1)} disabled={idx === 0}>
                            ↑
                          </Button>
                          <Button variant="outline" size="sm" className="size-8 rounded-xl px-0 text-[12px]" onClick={() => moveRule(idx, 1)} disabled={idx === rules.length - 1}>
                            ↓
                          </Button>
                          <Button variant="outline" size="sm" className="h-8 rounded-xl px-3 text-[12px] font-semibold" onClick={() => openEdit(idx)}>
                            编辑
                          </Button>
                          <Button variant="destructive" size="sm" className="h-8 gap-1.5 rounded-xl px-3 text-[12px] font-semibold" onClick={() => removeRule(idx)}>
                            <Trash2 className="size-3.5" />
                            删除
                          </Button>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 gap-2 text-[11px] md:grid-cols-3">
                        <div className="rounded-xl border border-slate-200/80 bg-slate-50/80 px-3 py-2">
                          <div className="font-mono text-[9px] font-black uppercase tracking-[0.15em] text-slate-400">match</div>
                          <div className="mt-1 truncate font-semibold text-slate-700">
                            {(r.match?.extensions || []).join(', ') || 'any file'}
                          </div>
                        </div>
                        <div className="rounded-xl border border-slate-200/80 bg-slate-50/80 px-3 py-2">
                          <div className="font-mono text-[9px] font-black uppercase tracking-[0.15em] text-slate-400">parse</div>
                          <div className="mt-1 truncate font-semibold text-slate-700">
                            {r.parser_backend || 'default'} · pre {r.preprocess?.enabled ? (r.preprocess?.steps || []).length : 0}
                          </div>
                        </div>
                        <div className="rounded-xl border border-slate-200/80 bg-slate-50/80 px-3 py-2">
                          <div className="font-mono text-[9px] font-black uppercase tracking-[0.15em] text-slate-400">chunk</div>
                          <div className="mt-1 truncate font-semibold text-slate-700">
                            {r.chunk_strategy || r.governance_profile_ref || 'dataset default'}
                          </div>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        <Badge variant="outline" className="rounded-lg border-slate-200 bg-slate-50/80 font-mono text-slate-600">
                          preprocess: {r.preprocess?.enabled ? (r.preprocess?.steps || []).length : 0}
                        </Badge>
                        {r.parser_backend ? <Badge variant="outline" className="rounded-lg border-slate-200 bg-slate-50/80 font-mono text-slate-600">parser: {r.parser_backend}</Badge> : null}
                        {r.chunk_strategy ? <Badge variant="outline" className="rounded-lg border-slate-200 bg-slate-50/80 font-mono text-slate-600">chunk: {r.chunk_strategy}</Badge> : null}
                        {r.governance_profile_ref ? <Badge variant="outline" className="rounded-lg border-slate-200 bg-slate-50/80 font-mono text-slate-600">profile: {r.governance_profile_ref}</Badge> : null}
                        {r.pipeline_patch && Object.keys(r.pipeline_patch || {}).length > 0 ? (
                          <Badge variant="outline" className="rounded-lg border-slate-200 bg-slate-50/80 font-mono text-slate-600">patch: {Object.keys(r.pipeline_patch || {}).length}</Badge>
                        ) : null}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Panel>

          <Panel variant="glass" className={cn(ingestionPanelClass, 'flex min-h-0 flex-col overflow-hidden')}>
            <div className={cn(ingestionPanelHeaderClass, 'space-y-3')}>
              <div className="flex items-start gap-3">
                <div className={ingestionIconPillClass}>
                  <Sparkles className="size-4 text-sky-600" />
                </div>
                <div className="min-w-0">
                  <div className="text-[15px] font-bold tracking-[-0.015em] text-slate-950 dark:text-foreground">入库预览（样例文件）</div>
                  <div className="mt-1 text-[12px] leading-5 text-slate-500 dark:text-muted-foreground">
                    上传样例文件，按当前策略执行：匹配规则 → 预处理 → 解析 → 治理 diff / 问题。
                  </div>
                </div>
              </div>
              <div className="rounded-[22px] border border-sky-100 bg-[linear-gradient(135deg,rgba(240,249,255,0.95),rgba(255,255,255,0.9))] p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.9),0_14px_32px_rgba(2,132,199,0.10)] dark:border-border/60 dark:bg-muted/20">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-400 dark:text-muted-foreground">sample file</span>
                  {previewFile ? <span className="truncate font-mono text-[11px] text-slate-600 dark:text-muted-foreground">{previewFile.name}</span> : null}
                </div>
                <div className="flex flex-col gap-2">
                  <Input
                    type="file"
                    className="h-10 w-full min-w-0 rounded-2xl border-slate-200 bg-white text-[11px] shadow-sm"
                    onChange={(e) => setPreviewFile(e.target.files?.[0] || null)}
                  />
                  <Button onClick={runPreview} disabled={!previewFile || previewing} className="h-10 w-full shrink-0 gap-2 rounded-2xl bg-slate-950 px-3 text-xs font-bold text-white shadow-[0_14px_28px_rgba(15,23,42,0.24)] hover:bg-slate-800">
                    {previewing ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Sparkles className="size-4" />}
                    生成预览
                  </Button>
                </div>
              </div>
            </div>

            {preview ? (
              <div className="min-h-0 flex-1 space-y-3 overflow-y-auto bg-[linear-gradient(180deg,rgba(248,250,252,0.62),rgba(255,255,255,0.92))] p-4 no-scrollbar dark:bg-muted/5">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge variant={preview.rule?.matched ? 'soft' : 'outline'} className="rounded-lg font-mono">
                    matched: {preview.rule?.matched ? 'true' : 'false'}
                  </Badge>
                  {preview.rule?.rule_name ? <Badge variant="outline" className="rounded-lg font-mono">{preview.rule.rule_name}</Badge> : null}
                  <Badge variant="outline" className="rounded-lg font-mono">parser: {preview.rule?.parser_backend}</Badge>
                  {preview.rule?.chunk_strategy ? <Badge variant="outline" className="rounded-lg font-mono">chunk: {preview.rule.chunk_strategy}</Badge> : null}
                  {preview.rule?.governance_profile_ref ? <Badge variant="outline" className="rounded-lg font-mono">profile: {preview.rule.governance_profile_ref}</Badge> : null}
                  <Badge variant="outline" className="rounded-lg font-mono">preprocess_changed: {String(preview.preprocess?.changed)}</Badge>
                </div>

                {Array.isArray(preview.clean?.issues) && preview.clean.issues.length > 0 ? (
                  <Panel variant="muted" className="rounded-2xl border-amber-200/70 bg-amber-50/70 p-4 shadow-none dark:border-amber-500/30 dark:bg-amber-500/10">
                    <div className="mb-2 text-sm font-bold text-slate-950 dark:text-foreground">后端检测到的问题（issues）</div>
                    <div className="space-y-2">
                      {preview.clean.issues.slice(0, 8).map((it) => (
                        <div key={`${it.code}-${it.message}`} className="text-xs leading-5 text-slate-700 dark:text-muted-foreground">
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

                <div className="grid grid-cols-1 gap-3">
                  <Panel variant="muted" className="overflow-hidden rounded-2xl border-slate-200/80 bg-white/78 p-0 shadow-none dark:border-border/60 dark:bg-card/60">
                    <div className="border-b border-border/60 px-4 py-3 text-sm font-bold">解析后 Markdown（raw）</div>
                    <pre className="max-h-[260px] overflow-y-auto whitespace-pre-wrap p-4 text-xs leading-relaxed no-scrollbar">
                      {preview.parse?.markdown || ''}
                    </pre>
                  </Panel>
                  <Panel variant="muted" className="overflow-hidden rounded-2xl border-slate-200/80 bg-white/78 p-0 shadow-none dark:border-border/60 dark:bg-card/60">
                    <div className="border-b border-border/60 px-4 py-3 text-sm font-bold">治理后 Markdown（clean）</div>
                    <pre className="max-h-[260px] overflow-y-auto whitespace-pre-wrap p-4 text-xs leading-relaxed no-scrollbar">
                      {preview.clean?.markdown || ''}
                    </pre>
                  </Panel>
                </div>

                {preview.clean?.diff_unified ? (
                  <Panel variant="muted" className="overflow-hidden rounded-2xl border-slate-200/80 bg-slate-950 p-0 text-slate-100 shadow-none dark:border-border/60">
                    <div className="border-b border-white/10 px-4 py-3 text-sm font-bold">Unified Diff（后端）</div>
                    <pre className="max-h-[320px] overflow-y-auto whitespace-pre p-4 font-mono text-xs leading-relaxed no-scrollbar">
                      {preview.clean.diff_unified}
                    </pre>
                  </Panel>
                ) : null}
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col justify-between bg-[linear-gradient(180deg,rgba(248,250,252,0.62),rgba(255,255,255,0.92))] p-4 dark:bg-muted/5">
                <div className="rounded-2xl border border-dashed border-slate-300 bg-white/68 px-4 py-5 text-[12px] leading-6 text-slate-500 dark:border-border dark:bg-muted/20 dark:text-muted-foreground">
                  可选：选择 HTML / PDF / DOCX / CSV 样例后生成预览，用于检查策略命中和治理 diff。
                </div>
                <div className="mt-4 grid gap-2 text-[11px] text-slate-500 dark:text-muted-foreground">
                  <div className="rounded-xl bg-slate-100/70 px-3 py-2 dark:bg-muted/30">1. 先确认命中规则是否符合预期</div>
                  <div className="rounded-xl bg-slate-100/70 px-3 py-2 dark:bg-muted/30">2. 再看解析后 Markdown 和治理后 Markdown 差异</div>
                  <div className="rounded-xl bg-slate-100/70 px-3 py-2 dark:bg-muted/30">3. 最后保存策略并重建相关索引</div>
                </div>
              </div>
            )}
          </Panel>
          </div>
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

      </PageScaffold>
    </AppFrame>
  )
}
