'use client'

import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Layers, Network, ShieldCheck, Sparkles, ChevronDown, type PlatformIcon } from '@/components/icons'
import { toast } from 'sonner'
import { SettingsSwitch } from '@/components/settings/settings-switch'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { toPrimitiveString } from '@/lib/primitive-text'
import { coerceOneOf } from '@/lib/one-of'
import { cn } from '@/lib/utils'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { parseChunkStrategyParamsJson } from '@/lib/chunk-strategy-params'
import type { DocumentPipelineOptions } from '@/types'
import styles from './pipeline-options-panel.module.css'

type PipelineOptionsPanelProps = {
  className?: string
  compact?: boolean
  value?: DocumentPipelineOptions
  enabled?: boolean
  onEnabledChange?: (value: boolean) => void
  onOptionChange?: <K extends keyof DocumentPipelineOptions>(key: K, value: DocumentPipelineOptions[K]) => void
  hideEnabledToggle?: boolean
  showJsonToolbar?: boolean
  showIndexingControls?: boolean
  layout?: 'panel' | 'form'
}

type PipelineIndexPreset = 'custom' | 'economical' | 'high_quality'

type BooleanOptionKey = keyof DocumentPipelineOptions

type NumberOptionKey = keyof DocumentPipelineOptions

type ToggleOptionItem = {
  key: BooleanOptionKey
  label: string
  hint: string
  dependsOn?: BooleanOptionKey
}

type NumberOptionItem = {
  key: NumberOptionKey
  label: string
  hint: string
  min: number
  max: number
  step: number
  dependsOn?: BooleanOptionKey
}

type OptionGroup = {
  title: string
  icon: PlatformIcon
  items: ToggleOptionItem[]
}

const PIPELINE_INDEX_PRESET_VALUES = ['custom', 'economical', 'high_quality'] as const
const GOVERNANCE_REMOVE_IMAGE_VALUES = ['none', 'decorative', 'all'] as const
const GOVERNANCE_REDACTION_MODE_VALUES = ['mask', 'token'] as const
const GOVERNANCE_KEYWORD_PROVIDER_VALUES = ['auto', 'jieba', 'jieba_textrank', 'hanlp', 'simple'] as const

const PIPELINE_INDEX_PRESETS: Record<
  PipelineIndexPreset,
  { label: string; description: string; patch: Partial<DocumentPipelineOptions> }
> = {
  custom: {
    label: '自定义',
    description: '保持当前配置',
    patch: {},
  },
  economical: {
    label: 'Economical (省成本)',
    description: '更少处理/存储，适合大规模导入',
    patch: {
      governance_enabled: false,
      persist_parsed_content: false,
      parse_fallback_enabled: false,
      near_dedup_enabled: false,
      embedding_context_prefix_enabled: false,
      chunk_vector_enabled: true,
      bm25_index_enabled: true,
      kg_enabled: false,
      event_vector_enabled: false,
      entity_vector_enabled: false,
      chunk_size: 1500,
      chunk_overlap: 150,
      chunk_merge_small_min_chars: 0,
    },
  },
  high_quality: {
    label: 'High-quality (高质量)',
    description: '更细切块+去重+上下文前缀，召回更稳',
    patch: {
      governance_enabled: true,
      persist_parsed_content: true,
      parse_fallback_enabled: true,
      near_dedup_enabled: true,
      embedding_context_prefix_enabled: true,
      chunk_vector_enabled: true,
      bm25_index_enabled: true,
      kg_enabled: true,
      event_vector_enabled: true,
      entity_vector_enabled: true,
      chunk_size: 900,
      chunk_overlap: 200,
      chunk_merge_small_min_chars: 160,
    },
  },
}

const PIPELINE_OPTION_LABELS: Partial<Record<keyof DocumentPipelineOptions, string>> = {
  governance_enabled: '治理清洗',
  persist_parsed_content: '持久化解析结果',
  parse_fallback_enabled: '解析回退',
  near_dedup_enabled: '跨文档近重复去重',
  embedding_context_prefix_enabled: 'Embedding 上下文前缀',
  chunk_vector_enabled: '向量索引 (Vector)',
  bm25_index_enabled: '全文索引 (BM25)',
  kg_enabled: 'KG 抽取',
  event_vector_enabled: '事件索引',
  entity_vector_enabled: '实体索引',
  chunk_size: 'chunk_size',
  chunk_overlap: 'chunk_overlap',
  chunk_merge_small_min_chars: '短块合并阈值',
}

type PipelinePresetDiffItem = {
  key: keyof DocumentPipelineOptions
  from: unknown
  to: unknown
}

function formatPipelineOptionValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'on' : 'off'
  if (typeof value === 'number' || typeof value === 'bigint' || typeof value === 'symbol') return toPrimitiveString(value)
  if (typeof value === 'string') return value
  if (value === null) return 'null'
  if (value === undefined) return 'unset'
  try {
    return JSON.stringify(value)
  } catch {
    return toPrimitiveString(value, 'unserializable')
  }
}

function detectPipelineIndexPreset(options: DocumentPipelineOptions): PipelineIndexPreset {
  const ids: PipelineIndexPreset[] = ['economical', 'high_quality']
  for (const id of ids) {
    const patch = PIPELINE_INDEX_PRESETS[id].patch
    let match = true
    for (const key of Object.keys(patch) as Array<keyof DocumentPipelineOptions>) {
      const expected = patch[key]
      if (expected === undefined) continue
      if (options[key] !== expected) {
        match = false
        break
      }
    }
    if (match) return id
  }
  return 'custom'
}

export function PipelineOptionsPanel(props: Readonly<PipelineOptionsPanelProps>) {
  const { className, compact } = props
  const formLayout = props.layout === 'form'
  const ctx = usePipelineOptions()
  const enabled = typeof props.enabled === 'boolean' ? props.enabled : ctx.enabled
  const options = props.value ?? ctx.options
  const setEnabled = props.onEnabledChange ?? ctx.setEnabled
  const updateOption = props.onOptionChange ?? ctx.updateOption
  const kgEnabled = !!options.kg_enabled
  const governanceEnabled = !!options.governance_enabled
  const governanceDisabled = !enabled || !governanceEnabled
  const pipelineDisabled = !enabled
  const showJsonToolbar = props.showJsonToolbar ?? !compact
  const showIndexingControls = props.showIndexingControls ?? true

  const [chunkStrategyParamsText, setChunkStrategyParamsText] = useState('')
  const [chunkStrategyParamsError, setChunkStrategyParamsError] = useState<string | null>(null)
  const [indexPresetDraft, setIndexPresetDraft] = useState<PipelineIndexPreset | null>(null)
  const [importDialogOpen, setImportDialogOpen] = useState(false)
  const [importText, setImportText] = useState('')

  useEffect(() => {
    try {
      const raw = options.chunk_strategy_params
      if (!raw || typeof raw !== 'object') {
        setChunkStrategyParamsText('')
      } else {
        setChunkStrategyParamsText(JSON.stringify(raw, null, 2))
      }
      setChunkStrategyParamsError(null)
    } catch {
      setChunkStrategyParamsText('')
      setChunkStrategyParamsError(null)
    }
  }, [options.chunk_strategy_params])

  const titleClasses = formLayout ? 'text-[14px] leading-6' : compact ? 'text-[13px] leading-5' : 'text-sm leading-5'
  const descClasses = formLayout ? 'text-[13px] leading-[22px]' : 'text-xs leading-5'
  const activeIndexPreset = useMemo(() => detectPipelineIndexPreset(options), [options])
  const pendingIndexPreset = useMemo(() => {
    if (!indexPresetDraft) return null
    if (indexPresetDraft === activeIndexPreset) return null
    if (indexPresetDraft === 'custom') return null
    return indexPresetDraft
  }, [activeIndexPreset, indexPresetDraft])
  const pendingPresetDiff = useMemo<PipelinePresetDiffItem[]>(() => {
    if (!pendingIndexPreset) return []
    const patch = PIPELINE_INDEX_PRESETS[pendingIndexPreset].patch
    const diffs: PipelinePresetDiffItem[] = []
    for (const key of Object.keys(patch) as Array<keyof DocumentPipelineOptions>) {
      const target = patch[key]
      if (target === undefined) continue
      const current = options[key]
      if (current === target) continue
      diffs.push({ key, from: current, to: target })
    }
    return diffs
  }, [options, pendingIndexPreset])
  const presetSelectValue = indexPresetDraft ?? activeIndexPreset

  const optionGroups = useMemo<OptionGroup[]>(() => {
    const groups: OptionGroup[] = [
      {
        title: '数据治理',
        icon: ShieldCheck,
        items: [
          {
            key: 'governance_enabled',
            label: '启用治理清洗',
            hint: '标准化 Markdown，清洗噪声',
          },
        ],
      },
    ]

    if (showIndexingControls) {
      groups.push(
        {
          title: '索引策略',
          icon: Layers,
          items: [
            {
              key: 'chunk_vector_enabled',
              label: '向量索引 (Vector)',
              hint: '语义检索核心能力',
            },
            {
              key: 'bm25_index_enabled',
              label: '全文索引 (BM25)',
              hint: '关键词精准匹配',
            },
          ],
        },
        {
          title: 'Embedding',
          icon: Sparkles,
          items: [
            {
              key: 'embedding_context_prefix_enabled',
              label: '结构化上下文前缀',
              hint: '在向量 embedding 前追加 header_path/outline 等轻量上下文（不改变正文与定位）',
              dependsOn: 'chunk_vector_enabled',
            },
          ],
        },
        {
          title: '知识图谱',
          icon: Network,
          items: [
            {
              key: 'kg_enabled',
              label: 'KG 抽取',
              hint: '提取实体与关系',
            },
            {
              key: 'event_vector_enabled',
              label: '事件索引',
              hint: '事件向量化',
              dependsOn: 'kg_enabled',
            },
            {
              key: 'entity_vector_enabled',
              label: '实体索引',
              hint: '实体向量化',
              dependsOn: 'kg_enabled',
            },
          ],
        }
      )
    }

    return groups
  }, [showIndexingControls])

  const governanceToggles: ToggleOptionItem[] = [
    {
        key: 'governance_extract_frontmatter',
        label: '提取 Frontmatter',
        hint: '读取 Markdown YAML frontmatter 作为元数据',
    },
    {
        key: 'governance_strip_frontmatter',
        label: '剥离 Frontmatter',
        hint: '提取后从正文中删除 frontmatter',
        dependsOn: 'governance_extract_frontmatter',
    },
    {
        key: 'governance_remove_toc_lines',
        label: '清理目录行',
        hint: '移除目录/索引类噪声',
    },
    {
        key: 'governance_remove_noise_lines',
        label: '过滤噪声行',
        hint: '移除符号占比过高的短行',
    },
    {
        key: 'governance_unwrap_lines',
        label: '合并软换行',
        hint: '拼接被换行切开的段落',
    },
    {
        key: 'governance_remove_common_lines',
        label: '去重页眉页脚',
        hint: '剔除跨页重复行',
    },
    {
        key: 'governance_remove_boilerplate',
        label: '移除样板信息',
        hint: '删除免责声明/致谢/版权等低价值内容',
    },
    {
        key: 'governance_normalize_urls',
        label: '规范化 URL',
        hint: '去追踪参、统一 URL 格式以便去重',
    },
    {
        key: 'governance_trim_references',
        label: '裁剪参考文献',
        hint: '裁剪文末 References/Bibliography（保守）',
    },
    {
        key: 'governance_drop_duplicate_paragraphs',
        label: '段落重复块去重',
        hint: '删除文内重复出现多次的段落块',
    },
    {
        key: 'governance_normalize_tables',
        label: '规范化表格',
        hint: '对 Markdown pipe 表格做对齐/裁剪',
    },
    {
        key: 'governance_strip_code_line_numbers',
        label: '移除代码行号',
        hint: '对 fenced code 内的行号做最佳努力去除',
    },
    {
        key: 'governance_detect_language',
        label: '检测语言',
        hint: '识别 zh/en/mixed 写入元数据',
    },
    {
        key: 'governance_extract_keywords',
        label: '抽取关键词',
        hint: '提取文档级关键词写入元数据',
    },
    {
        key: 'governance_pii_anonymize',
        label: '匿名化隐私信息',
        hint: '邮箱/电话/身份证/卡号等脱敏',
    },
    {
        key: 'governance_secrets_redact',
        label: '脱敏密钥/Token',
        hint: 'API Key/私钥/Bearer token 等脱敏',
    },
    {
        key: 'governance_drop_outline_only',
        label: '丢弃大纲文档',
        hint: '仅标题/目录为主的文档将被过滤',
    },
    {
        key: 'governance_drop_low_density',
        label: '丢弃低密度文本',
        hint: '乱码/符号占比过高将被过滤',
    },
    {
        key: 'governance_quarantine_on_drop',
        label: '隔离而非失败',
        hint: '触发质量过滤时标记 quarantined，便于人工复核',
    },
]

  const governanceNumbers: NumberOptionItem[] = [
    {
        key: 'governance_language_min_chars',
        label: '语言最小字符',
        hint: '内容太短时不做语言检测',
        min: 0,
        max: 200000,
        step: 10,
        dependsOn: 'governance_detect_language',
    },
    {
        key: 'governance_max_blank_lines',
        label: '最大空行数',
        hint: '0 合并段落；2 强分段',
        min: 0,
        max: 10,
        step: 1,
    },
    {
        key: 'governance_unwrap_max_line_length',
        label: '最大行长',
        hint: '超过长度不再合并',
        min: 40,
        max: 400,
        step: 10,
    },
    {
        key: 'governance_noise_ratio_threshold',
        label: '噪声阈值',
        hint: '越低过滤越激进',
        min: 0,
        max: 1,
        step: 0.05,
    },
    {
        key: 'governance_noise_min_chars',
        label: '最小字符数',
        hint: '短行低于该值会剔除',
        min: 1,
        max: 20,
        step: 1,
    },
    {
        key: 'governance_common_lines_min_ratio',
        label: '重复行比例',
        hint: '跨页重复比例阈值',
        min: 0,
        max: 1,
        step: 0.05,
    },
    {
        key: 'governance_common_lines_min_docs',
        label: '重复行文档数',
        hint: '至少出现的页数',
        min: 2,
        max: 50,
        step: 1,
    },
    {
        key: 'governance_drop_duplicate_paragraphs_min_occurrences',
        label: '段落去重次数',
        hint: '重复次数达到该值才移除',
        min: 2,
        max: 100,
        step: 1,
        dependsOn: 'governance_drop_duplicate_paragraphs',
    },
    {
        key: 'governance_drop_duplicate_paragraphs_min_chars',
        label: '段落最小字符',
        hint: '太短的段落不参与去重',
        min: 0,
        max: 50000,
        step: 10,
        dependsOn: 'governance_drop_duplicate_paragraphs',
    },
    {
        key: 'governance_drop_duplicate_paragraphs_max_chars',
        label: '段落最大字符',
        hint: '过长段落不参与去重（0 表示不限制）',
        min: 0,
        max: 200000,
        step: 50,
        dependsOn: 'governance_drop_duplicate_paragraphs',
    },
    {
        key: 'governance_drop_outline_min_content_chars',
        label: '大纲最小内容量',
        hint: '少于该值才触发过滤',
        min: 0,
        max: 200000,
        step: 50,
    },
    {
        key: 'governance_drop_outline_max_heading_ratio',
        label: '大纲标题比例',
        hint: '越低越严格',
        min: 0,
        max: 1,
        step: 0.05,
    },
    {
        key: 'governance_drop_low_density_threshold',
        label: '低密度阈值',
        hint: '越高越严格',
        min: 0,
        max: 1,
        step: 0.02,
    },
]

  const pipelineToggles: ToggleOptionItem[] = [
    {
        key: 'parse_fallback_enabled',
        label: '解析回退',
        hint: '解析质量差时尝试其他后端（PDF）',
    },
    {
        key: 'persist_parsed_content',
        label: '持久化解析结果',
        hint: '保存 raw+clean markdown 便于审计/回溯',
    },
    {
        key: 'near_dedup_enabled',
        label: '跨文档近重复去重',
        hint: 'SimHash 去除跨文档重复 chunks',
    },
]

  const pipelineNumbers: NumberOptionItem[] = [
    {
        key: 'chunk_merge_small_min_chars',
        label: '短块合并阈值',
        hint: '将极短 chunk 与相邻 chunk 合并（0 关闭），可减少过碎片化与噪声',
        min: 0,
        max: 10000,
        step: 10,
    },
    {
        key: 'parse_fallback_min_content_chars',
        label: '回退最小内容',
        hint: '少于该值认为解析失败',
        min: 0,
        max: 200000,
        step: 10,
        dependsOn: 'parse_fallback_enabled',
    },
    {
        key: 'parse_fallback_max_retries',
        label: '回退重试次数',
        hint: '最多尝试次数',
        min: 0,
        max: 3,
        step: 1,
        dependsOn: 'parse_fallback_enabled',
    },
    {
        key: 'persist_parsed_content_max_chars',
        label: '持久化最大字符',
        hint: '过大时截断保存',
        min: 0,
        max: 2000000,
        step: 1000,
        dependsOn: 'persist_parsed_content',
    },
    {
        key: 'near_dedup_hamming_threshold',
        label: '近重复阈值',
        hint: 'SimHash 汉明距离阈值',
        min: 0,
        max: 64,
        step: 1,
        dependsOn: 'near_dedup_enabled',
    },
    {
        key: 'near_dedup_max_bucket_size',
        label: '去重桶最大值',
        hint: '控制索引体积与误判风险',
        min: 8,
        max: 100000,
        step: 8,
        dependsOn: 'near_dedup_enabled',
    },
]

  const handleChecked = (key: keyof typeof options, value: boolean) => {
    updateOption(key, value === true)
  }

  const handleNumberChange = <K extends keyof typeof options>(key: K, value: number) => {
    if (!Number.isFinite(value)) return
    updateOption(key, value as (typeof options)[K])
  }

  const validateAndApplyChunkStrategyParams = (text: string) => {
    const res = parseChunkStrategyParamsJson(text)
    if (!res.ok) {
      setChunkStrategyParamsError(res.error)
      return
    }
    setChunkStrategyParamsError(null)
    updateOption('chunk_strategy_params', res.value)
  }

  const exportPipelineJson = async () => {
    const text = ctx.exportJson()
    try {
      await navigator.clipboard.writeText(text)
      toast.success('已复制管线 JSON')
    } catch {
      toast.error('复制失败（浏览器未授权剪贴板）')
    }
  }

  const importPipelineJson = () => {
    const text = (importText || '').trim()
    if (!text) {
      toast.error('请输入 JSON')
      return
    }
    const res = ctx.importJson(text)
    if (!res.ok) {
      toast.error(res.error || '导入失败')
      return
    }
    toast.success('已导入管线 JSON')
    setImportDialogOpen(false)
    setImportText('')
  }

  const applyIndexPreset = (preset: PipelineIndexPreset) => {
    if (preset === 'custom') return

    // Choosing a preset implies enabling the pipeline (for the current UI surface).
    if (!enabled) setEnabled(true)

    const patch = PIPELINE_INDEX_PRESETS[preset].patch
    for (const key of Object.keys(patch) as Array<keyof DocumentPipelineOptions>) {
      const value = patch[key]
      if (value === undefined) continue
      updateOption(key, value)
    }
    toast.success(`已应用索引模式：${PIPELINE_INDEX_PRESETS[preset].label}`)
  }

  const pipelinePanelClass = cn(
    formLayout ? 'font-sans' : compact ? "space-y-4 font-sans" : "space-y-5 font-sans",
    formLayout && styles.form,
    className
  )
  const toggleRowClass = formLayout ? styles.enabledRow : 'flex items-center justify-between gap-3 border-b border-border/60 pb-4'
  const indexPresetClass = 'border-b border-border/60 pb-4'
  const jsonToolbarClass = cn(
    'flex items-center gap-2 border-b border-border/60 pb-3',
    compact ? 'justify-between' : 'justify-end'
  )
  const jsonButtonClass =
    'h-11 px-3 text-xs shadow-none sm:h-8'
  const numberFieldLabelClass =
    'flex items-center justify-between gap-3 text-xs font-medium leading-5 text-muted-foreground'
  const numberFieldLabelTextClass =
    'min-w-0 flex-1 text-xs font-medium leading-5 text-muted-foreground'
  const fieldInputClass = 'h-11 bg-background text-[13px] sm:h-8'

  return (
    <div className={pipelinePanelClass}>
      {!props.hideEnabledToggle && (
        <div className={toggleRowClass}>
          <div>
            <div className={cn("font-semibold tracking-[-0.01em] text-foreground/85", titleClasses)}>
              自定义管线
            </div>
            <p className={cn("mt-0.5 text-muted-foreground", descClasses)}>
              开启后可配置详细的处理流程
            </p>
          </div>
          <SettingsSwitch
            aria-label="切换自定义管线"
            checked={enabled}
            onCheckedChange={(value) => setEnabled(value === true)}
          />
        </div>
      )}

      {showIndexingControls && (
        <details className={formLayout ? styles.preset : indexPresetClass} open={formLayout ? undefined : true}>
          {formLayout && <summary>索引模式<ChevronDown className="size-3.5" /></summary>}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className={cn("font-semibold tracking-[-0.01em] text-foreground/85", titleClasses)}>索引模式（成本/质量）</div>
              <p className={cn("mt-0.5 text-muted-foreground", descClasses)}>
                先预览改动再应用，也可逐项调整。
              </p>
            </div>
            <Select
              value={presetSelectValue}
              onValueChange={(value) => {
                const next = coerceOneOf(PIPELINE_INDEX_PRESET_VALUES, value, activeIndexPreset)
                if (next === 'custom') {
                  setIndexPresetDraft(null)
                  return
                }
                if (next === activeIndexPreset) {
                  setIndexPresetDraft(null)
                  return
                }
                setIndexPresetDraft(next)
              }}
            >
              <SelectTrigger aria-label="索引模式" className="h-11 w-full shrink-0 bg-background text-[13px] shadow-none sm:h-9 sm:w-52">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="custom">自定义</SelectItem>
                <SelectItem value="economical">Economical (省成本)</SelectItem>
                <SelectItem value="high_quality">High-quality (高质量)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {pendingIndexPreset ? (
            <div className="mt-4 border-l-2 border-border pl-3">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className={cn("font-medium text-foreground/80", compact ? "text-xs" : "text-sm")}>
                    将应用：{PIPELINE_INDEX_PRESETS[pendingIndexPreset].label}
                  </div>
                  <div className="text-xs leading-5 text-muted-foreground">
                    {PIPELINE_INDEX_PRESETS[pendingIndexPreset].description} · 预计修改 {pendingPresetDiff.length} 项
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-11 sm:h-8"
                    onClick={() => setIndexPresetDraft(null)}
                  >
                    取消
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    className="h-11 shadow-none sm:h-8"
                    onClick={() => {
                      applyIndexPreset(pendingIndexPreset)
                      setIndexPresetDraft(null)
                    }}
                  >
                    应用
                  </Button>
                </div>
              </div>

              <details className="mt-2 group/details">
                <summary className={cn(
                  "cursor-pointer select-none flex items-center justify-between gap-2 rounded-md px-2 py-1 hover:bg-muted/60 transition-colors",
                  "text-xs"
                )}>
                  <span className="text-muted-foreground">查看变更</span>
                  <ChevronDown className="size-3 text-muted-foreground transition-transform group-open/details:rotate-180" />
                </summary>
                <div className="mt-2 grid gap-1.5 px-2">
                  {pendingPresetDiff.map((d) => {
                    const label = PIPELINE_OPTION_LABELS[d.key] || String(d.key)
                    return (
                      <div key={String(d.key)} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs">
                        <span className="text-muted-foreground truncate">{label}</span>
                        <span className="font-mono text-foreground/80 shrink-0">
                          {formatPipelineOptionValue(d.from)} → {formatPipelineOptionValue(d.to)}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </details>
            </div>
          ) : null}
        </details>
      )}

      {showJsonToolbar && (
        <div className={jsonToolbarClass}>
          {compact ? (
            <div className="min-w-0 leading-none">
              <span className="block text-[13px] font-medium text-foreground">高级配置</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">JSON 导入导出</span>
            </div>
          ) : null}
          <div className="flex shrink-0 items-center gap-1">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-11 px-3 text-xs text-muted-foreground sm:h-8"
              onClick={() => {
                ctx.reset()
                toast.message('已重置为默认管线')
              }}
            >
              重置
            </Button>
            <Dialog
              open={importDialogOpen}
              onOpenChange={(next) => {
                setImportDialogOpen(next)
                if (next) setImportText('')
              }}
            >
              <DialogTrigger asChild>
                <Button type="button" variant="outline" size="sm" className={jsonButtonClass}>
                  导入
                </Button>
              </DialogTrigger>
              <DialogContent className="max-h-[calc(100dvh-2rem)] max-w-2xl overflow-y-auto overscroll-contain">
                <DialogHeader>
                  <DialogTitle>导入管线 JSON</DialogTitle>
                  <DialogDescription>
                    粘贴管线 JSON（支持 <span className="font-mono">{'{enabled, options}'}</span> 或仅 <span className="font-mono">options</span>）
                  </DialogDescription>
                </DialogHeader>

                <Textarea
                  value={importText}
                  onChange={(e) => setImportText(e.target.value)}
                  placeholder='例如：{"enabled": true, "options": {"chunk_size": 900}}'
                  className="min-h-[220px] font-mono text-xs"
                />

                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => setImportDialogOpen(false)}>
                    取消
                  </Button>
                  <Button type="button" onClick={importPipelineJson} disabled={!importText.trim()}>
                    导入
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
            <Button type="button" variant="outline" size="sm" className={jsonButtonClass} onClick={exportPipelineJson}>
              导出
            </Button>
          </div>
        </div>
      )}

      <div className="grid divide-y divide-border/60">
        {optionGroups.map((group) => {
          const Icon = group.icon
          return (
            <div
              key={group.title}
              className={cn(
                formLayout ? styles.group : "min-w-0 py-4 first:pt-0 last:pb-0",
                !enabled && "grayscale-[0.5] pointer-events-none"
              )}
            >
              <div className={formLayout ? styles.groupTitle : "mb-3 flex items-center gap-2"}>
                <Icon className="size-4 shrink-0 text-muted-foreground" />
                <span className={cn("font-medium text-foreground", titleClasses)}>{group.title}</span>
              </div>

              <div className={cn(formLayout ? styles.options : 'space-y-3', formLayout && group.title === '索引策略' && styles.paired, formLayout && group.title === '知识图谱' && styles.graph)}>
                {group.items.map((item) => {
                  const depends = item.dependsOn === 'kg_enabled'
                  const disabled = !enabled || (depends && !kgEnabled)
                  const checked = !!options[item.key]
                  return (
                    <div key={item.key} className={formLayout ? styles.optionRow : "flex items-center justify-between gap-3"}>
                      <div className="flex-1 min-w-0">
                        <div className={cn("font-medium text-foreground", titleClasses)}>
                          {item.label}
                        </div>
                        <p className={cn("text-muted-foreground", descClasses, formLayout && group.title === '知识图谱' && 'sr-only')}>
                          {item.hint}
                        </p>
                      </div>
                      <SettingsSwitch
                        aria-label={`切换${item.label}`}
                        checked={checked}
                        onCheckedChange={(value) => handleChecked(item.key, value)}
                        disabled={disabled}
                        className="shrink-0"
                      />
                    </div>
                  )
                })}
              </div>

              {group.title === '数据治理' && (
                <div className="mt-3">
                  <details className="group/details">
                    <summary className={cn("flex min-h-11 cursor-pointer list-none select-none items-center justify-between rounded-md text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:min-h-9", descClasses)}>
                      <span>高级治理参数</span>
                      <ChevronDown className="size-3 transition-transform group-open/details:rotate-180" />
                    </summary>
                    <div className="space-y-4 border-l border-border/60 pl-3">
                      <div className="space-y-2 pt-2">
                        <div className="text-[13px] font-medium text-foreground">
                          治理清洗
                        </div>
                        <div className="space-y-3">
                          {governanceToggles.map((item) => {
                            const checked = !!options[item.key]
                            const dependsOn = item.dependsOn
                            const disabled = governanceDisabled || (dependsOn ? !options[dependsOn] : false)
                            return (
                              <div key={item.key} className="flex items-center justify-between gap-3">
                                <div className="flex-1 min-w-0">
                                  <div className={cn("font-medium text-foreground", titleClasses)}>
                                    {item.label}
                                  </div>
                                  <p className={cn("text-muted-foreground", descClasses)}>
                                    {item.hint}
                                  </p>
                                </div>
                                <SettingsSwitch
                                  aria-label={`切换${item.label}`}
                                  checked={checked}
                                  onCheckedChange={(value) => handleChecked(item.key, value)}
                                  disabled={disabled}
                                  className="shrink-0"
                                />
                              </div>
                            )
                          })}
                        </div>
                      </div>

                      {/* Image removal */}
                      <div className="space-y-1.5">
                        <div className="text-xs font-medium text-muted-foreground">图片处理</div>
                        <Select
                          value={options.governance_remove_images || 'none'}
                          onValueChange={(value) => updateOption('governance_remove_images', coerceOneOf(GOVERNANCE_REMOVE_IMAGE_VALUES, value, 'none'))}
                          disabled={governanceDisabled}
                        >
                          <SelectTrigger aria-label="图片处理" className={fieldInputClass}>
                            <SelectValue placeholder="选择方式" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">保留图片</SelectItem>
                            <SelectItem value="decorative">删除装饰图</SelectItem>
                            <SelectItem value="all">删除全部图片</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      {/* URL tracking params */}
                      {!governanceDisabled && options.governance_normalize_urls && (
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <div className={cn("font-medium text-foreground", titleClasses)}>
                              去追踪参数
                            </div>
                            <p className={cn("text-muted-foreground", descClasses)}>
                              移除 utm_* / gclid / fbclid 等
                            </p>
                          </div>
                          <SettingsSwitch
                            aria-label="切换去追踪参数"
                            checked={!!options.governance_normalize_urls_strip_tracking}
                            onCheckedChange={(value) => handleChecked('governance_normalize_urls_strip_tracking', value)}
                            disabled={governanceDisabled}
                            className="shrink-0"
                          />
                        </div>
                      )}

                      {/* PII settings */}
                      {!governanceDisabled && options.governance_pii_anonymize && (
                        <div className="space-y-1.5">
                          <div className="text-xs font-medium text-muted-foreground">隐私脱敏配置</div>
                          <div className="grid grid-cols-2 gap-2">
                            <Select
                              value={options.governance_pii_mode || 'mask'}
                              onValueChange={(value) => updateOption('governance_pii_mode', coerceOneOf(GOVERNANCE_REDACTION_MODE_VALUES, value, 'mask'))}
                              disabled={governanceDisabled}
                            >
                              <SelectTrigger aria-label="隐私脱敏模式" className={fieldInputClass}>
                                <SelectValue placeholder="模式" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="mask">掩码替换</SelectItem>
                                <SelectItem value="token">占位符</SelectItem>
                              </SelectContent>
                            </Select>
                            <Input
                              value={options.governance_pii_mask || ''}
                              disabled={governanceDisabled || options.governance_pii_mode === 'token'}
                              onChange={(e) => updateOption('governance_pii_mask', e.currentTarget.value)}
                              placeholder="[REDACTED]"
                              aria-label="隐私脱敏替换文本"
                              className={fieldInputClass}
                            />
                          </div>
                        </div>
                      )}

                      {/* Secrets settings */}
                      {!governanceDisabled && options.governance_secrets_redact && (
                        <div className="space-y-1.5">
                          <div className="text-xs font-medium text-muted-foreground">密钥脱敏配置</div>
                          <div className="grid grid-cols-2 gap-2">
                            <Select
                              value={options.governance_secrets_mode || 'mask'}
                              onValueChange={(value) => updateOption('governance_secrets_mode', coerceOneOf(GOVERNANCE_REDACTION_MODE_VALUES, value, 'mask'))}
                              disabled={governanceDisabled}
                            >
                              <SelectTrigger aria-label="密钥脱敏模式" className={fieldInputClass}>
                                <SelectValue placeholder="模式" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="mask">掩码替换</SelectItem>
                                <SelectItem value="token">占位符</SelectItem>
                              </SelectContent>
                            </Select>
                            <Input
                              value={options.governance_secrets_mask || ''}
                              disabled={governanceDisabled || options.governance_secrets_mode === 'token'}
                              onChange={(e) => updateOption('governance_secrets_mask', e.currentTarget.value)}
                              placeholder="[SECRET]"
                              aria-label="密钥脱敏替换文本"
                              className={fieldInputClass}
                            />
                          </div>
                        </div>
                      )}

                      {/* Keyword settings */}
                      {!governanceDisabled && options.governance_extract_keywords && (
                        <div className="space-y-2">
                          <div className="text-xs font-medium text-muted-foreground">关键词抽取配置</div>
                          <div className="grid grid-cols-2 gap-2">
                            <Select
                              value={options.governance_keywords_provider || 'auto'}
                              onValueChange={(value) => updateOption('governance_keywords_provider', coerceOneOf(GOVERNANCE_KEYWORD_PROVIDER_VALUES, value, 'auto'))}
                              disabled={governanceDisabled}
                            >
                              <SelectTrigger aria-label="关键词抽取方式" className={fieldInputClass}>
                                <SelectValue placeholder="Provider" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="auto">auto</SelectItem>
                                <SelectItem value="jieba">jieba</SelectItem>
                                <SelectItem value="jieba_textrank">jieba_textrank</SelectItem>
                                <SelectItem value="hanlp">hanlp</SelectItem>
                                <SelectItem value="simple">simple</SelectItem>
                              </SelectContent>
                            </Select>
                            <Input
                              type="number"
                              value={typeof options.governance_keywords_top_k === 'number' ? options.governance_keywords_top_k : ''}
                              min={1}
                              max={100}
                              step={1}
                              disabled={governanceDisabled}
                              onChange={(e) => handleNumberChange('governance_keywords_top_k', e.currentTarget.valueAsNumber)}
                              aria-label="关键词数量"
                              className={fieldInputClass}
                              placeholder="Top K"
                            />
                          </div>
                          <Input
                            type="number"
                            value={typeof options.governance_keywords_max_chars === 'number' ? options.governance_keywords_max_chars : ''}
                            min={0}
                            max={2000000}
                            step={1000}
                            disabled={governanceDisabled}
                            onChange={(e) => handleNumberChange('governance_keywords_max_chars', e.currentTarget.valueAsNumber)}
                            aria-label="关键词抽取最大字符"
                            className={fieldInputClass}
                            placeholder="关键词抽取最大字符"
                          />
                        </div>
                      )}

                      {/* HTML XPath */}
                      <div className="space-y-1.5">
                        <div className="flex justify-between">
                           <div className="text-xs font-medium text-muted-foreground">HTML 提取 (XPath)</div>
                        </div>
                        <Input
                          value={options.governance_html_xpath || ''}
                          disabled={governanceDisabled}
                          onChange={(e) => updateOption('governance_html_xpath', e.currentTarget.value)}
                          placeholder="//article | //main"
                          aria-label="HTML 提取 XPath"
                          className={cn(fieldInputClass, 'font-mono')}
                        />
                      </div>

                      <div className="grid gap-3 pt-1">
                        {governanceNumbers.map((item) => {
                          const value = options[item.key]
                          const dependsOn = item.dependsOn
                          const shouldHide =
                            (item.key === 'governance_drop_outline_min_content_chars' || item.key === 'governance_drop_outline_max_heading_ratio') &&
                            !options.governance_drop_outline_only
                          const shouldHideLowDensity = item.key === 'governance_drop_low_density_threshold' && !options.governance_drop_low_density
                          const shouldHideDepends = dependsOn ? !options[dependsOn] : false
                          if (shouldHide || shouldHideLowDensity || shouldHideDepends) return null
                          return (
                            <label key={item.key} className={numberFieldLabelClass}>
                              <span className={numberFieldLabelTextClass} title={item.hint}>{item.label}</span>
                              <Input
                                type="number"
                                value={typeof value === 'number' ? value : ''}
                                min={item.min}
                                max={item.max}
                                step={item.step}
                                disabled={governanceDisabled}
                                onChange={(e) => handleNumberChange(item.key, e.currentTarget.valueAsNumber)}
                                className={cn(fieldInputClass, 'w-20 shrink-0 px-2 text-right')}
                              />
                            </label>
                          )
                        })}
                      </div>

                      <div className="pt-2 border-t border-border/60 space-y-2">
                        <div className="text-[13px] font-medium text-foreground">
                          解析与去重
                        </div>
                        <div className="space-y-3">
                          {pipelineToggles.map((item) => {
                            const checked = !!options[item.key]
                            return (
                              <div key={item.key} className="flex items-center justify-between gap-3">
                                <div className="flex-1 min-w-0">
                                  <div className={cn("font-medium text-foreground", titleClasses)}>
                                    {item.label}
                                  </div>
                                  <p className={cn("text-muted-foreground", descClasses)}>
                                    {item.hint}
                                  </p>
                                </div>
                                <SettingsSwitch
                                  aria-label={`切换${item.label}`}
                                  checked={checked}
                                  onCheckedChange={(value) => handleChecked(item.key, value)}
                                  disabled={pipelineDisabled}
                                  className="shrink-0"
                                />
                              </div>
                            )
                          })}
                        </div>

                        <div className="grid gap-3 pt-1">
                          {pipelineNumbers.map((item) => {
                            const value = options[item.key]
                            const dependsOn = item.dependsOn
                            const shouldHide = dependsOn ? !options[dependsOn] : false
                            if (shouldHide) return null
                            return (
                              <label key={item.key} className={numberFieldLabelClass}>
                                <span className={numberFieldLabelTextClass} title={item.hint}>{item.label}</span>
                                <Input
                                  type="number"
                                  value={typeof value === 'number' ? value : ''}
                                  min={item.min}
                                  max={item.max}
                                  step={item.step}
                                  disabled={pipelineDisabled}
                                  onChange={(e) => handleNumberChange(item.key, e.currentTarget.valueAsNumber)}
                                  className={cn(fieldInputClass, 'w-20 shrink-0 px-2 text-right')}
                                />
                              </label>
                            )
                          })}
                        </div>

                        <div className="pt-2 border-t border-border/60 space-y-2">
                          <div className="text-[13px] font-medium text-foreground">
                            切块策略参数（高级）
                          </div>
                          <Textarea
                            value={chunkStrategyParamsText}
                            onChange={(e) => {
                              const v = e.currentTarget.value
                              setChunkStrategyParamsText(v)
                              validateAndApplyChunkStrategyParams(v)
                            }}
                            disabled={pipelineDisabled}
                            aria-label="切块策略参数 JSON"
                            className="min-h-[84px] bg-background font-mono text-xs"
                            placeholder='例如：{ "child_ratio": 0.25, "min_child_size": 300 }'
                          />
                          {chunkStrategyParamsError ? (
                            <div className="rounded-md border border-warning/25 bg-warning/10 px-2 py-1 text-xs text-warning">
                              {chunkStrategyParamsError}
                            </div>
                          ) : (
                            <div className="text-xs leading-5 text-muted-foreground">
                              仅允许小型 JSON 对象（primitive values），后端会做同样的安全校验；显式参数将覆盖数据集/默认值
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </details>
                </div>
              )}

              {group.title === '知识图谱' && !kgEnabled && (
                <div
                  className={cn(
                    "mt-3 flex items-center gap-1.5 text-xs leading-5 text-muted-foreground"
                  )}
                >
                  <Sparkles className="size-3 text-muted-foreground/60" />
                  需先开启 KG 抽取才能配置索引
                </div>
              )}
            </div>
          )
        })}
      </div>

      {enabled && (
        <div className={cn("flex items-center justify-center gap-1.5 text-muted-foreground mt-2", descClasses)}>
          <CheckCircle2 className="size-3" />
          <span>自定义配置已生效</span>
        </div>
      )}
    </div>
  )
}
