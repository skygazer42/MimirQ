'use client'

import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Layers, Network, ShieldCheck, Sparkles, ChevronDown } from 'lucide-react'
import { toast } from 'sonner'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { parseChunkStrategyParamsJson } from '@/lib/chunk-strategy-params'
import type { DocumentPipelineOptions } from '@/types'

type PipelineOptionsPanelProps = {
  className?: string
  compact?: boolean
  value?: DocumentPipelineOptions
  enabled?: boolean
  onEnabledChange?: (value: boolean) => void
  onOptionChange?: <K extends keyof DocumentPipelineOptions>(key: K, value: DocumentPipelineOptions[K]) => void
  hideEnabledToggle?: boolean
}

type PipelineIndexPreset = 'custom' | 'economical' | 'high_quality'

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
      kg_enabled: false,
      event_vector_enabled: false,
      entity_vector_enabled: false,
      chunk_size: 900,
      chunk_overlap: 200,
      chunk_merge_small_min_chars: 160,
    },
  },
}

function detectPipelineIndexPreset(options: DocumentPipelineOptions): PipelineIndexPreset {
  const ids: PipelineIndexPreset[] = ['economical', 'high_quality']
  for (const id of ids) {
    const patch = PIPELINE_INDEX_PRESETS[id].patch
    let match = true
    for (const [rawKey, expected] of Object.entries(patch)) {
      const key = rawKey as keyof DocumentPipelineOptions
      if (typeof expected === 'undefined') continue
      if ((options as any)?.[key] !== expected) {
        match = false
        break
      }
    }
    if (match) return id
  }
  return 'custom'
}

export function PipelineOptionsPanel(props: PipelineOptionsPanelProps) {
  const { className, compact } = props
  const ctx = usePipelineOptions()
  const enabled = typeof props.enabled === 'boolean' ? props.enabled : ctx.enabled
  const options = props.value ?? ctx.options
  const setEnabled = props.onEnabledChange ?? ctx.setEnabled
  const updateOption = props.onOptionChange ?? ctx.updateOption
  const kgEnabled = !!options.kg_enabled
  const governanceEnabled = !!options.governance_enabled
  const governanceDisabled = !enabled || !governanceEnabled
  const pipelineDisabled = !enabled

  const [chunkStrategyParamsText, setChunkStrategyParamsText] = useState('')
  const [chunkStrategyParamsError, setChunkStrategyParamsError] = useState<string | null>(null)

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

  const titleClasses = compact ? 'text-xs' : 'text-sm'
  const descClasses = compact ? 'text-[10px]' : 'text-xs'
  const activeIndexPreset = useMemo(() => detectPipelineIndexPreset(options), [options])

  const optionGroups = useMemo(() => ([
    {
      title: '数据治理',
      icon: ShieldCheck,
      color: 'text-sky-600 dark:text-sky-300',
      bgColor: 'bg-sky-500/10 dark:bg-sky-500/20',
      items: [
        {
          key: 'governance_enabled',
          label: '启用治理清洗',
          hint: '标准化 Markdown，清洗噪声',
        },
      ],
    },
    {
      title: '索引策略',
      icon: Layers,
      color: 'text-sky-600 dark:text-sky-300',
      bgColor: 'bg-sky-500/10 dark:bg-sky-500/20',
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
      color: 'text-emerald-600 dark:text-emerald-300',
      bgColor: 'bg-emerald-500/10 dark:bg-emerald-500/20',
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
      color: 'text-purple-600 dark:text-purple-300',
      bgColor: 'bg-purple-500/10 dark:bg-purple-500/20',
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
    },
  ]), [])

  const governanceToggles = [
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
  ] as const

  const governanceNumbers = [
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
  ] as const

  const pipelineToggles = [
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
  ] as const

  const pipelineNumbers = [
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
  ] as const

  const handleChecked = (key: keyof typeof options, value: boolean | 'indeterminate') => {
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
    const text = window.prompt('粘贴管线 JSON（支持 {enabled, options} 或仅 options）')
    if (!text) return
    const res = ctx.importJson(text)
    if (!res.ok) {
      toast.error(res.error || '导入失败')
      return
    }
    toast.success('已导入管线 JSON')
  }

  const applyIndexPreset = (preset: PipelineIndexPreset) => {
    if (preset === 'custom') return

    // Choosing a preset implies enabling the pipeline (for the current UI surface).
    if (!enabled) setEnabled(true)

    const patch = PIPELINE_INDEX_PRESETS[preset].patch
    for (const [rawKey, value] of Object.entries(patch)) {
      if (typeof value === 'undefined') continue
      updateOption(rawKey as keyof DocumentPipelineOptions, value as any)
    }
    toast.success(`已应用索引模式：${PIPELINE_INDEX_PRESETS[preset].label}`)
  }

  return (
    <div className={cn("space-y-4 font-sans", className)}>
      {!props.hideEnabledToggle && (
        <div className="flex items-center justify-between p-3 rounded-xl bg-muted border border-border">
          <div>
            <div className={cn("font-semibold text-foreground", titleClasses)}>
              自定义管线
            </div>
            <p className={cn("text-muted-foreground", descClasses)}>
              开启后可配置详细的处理流程
            </p>
          </div>
          <Switch
            checked={enabled}
            onCheckedChange={(value) => setEnabled(value === true)}
          />
        </div>
      )}

      <div className={cn("flex items-center justify-between gap-3 rounded-xl border border-border bg-muted/30", compact ? "px-2.5 py-2" : "p-3")}>
        <div className="min-w-0">
          <div className={cn("font-semibold text-foreground", titleClasses)}>索引模式（成本/质量）</div>
          <p className={cn("text-muted-foreground", descClasses)}>
            {compact ? 'Economical / High-quality presets' : '一键套用常见预设；你仍可继续逐项微调。'}
          </p>
        </div>
        <Select value={activeIndexPreset} onValueChange={(v) => applyIndexPreset(v as PipelineIndexPreset)}>
          <SelectTrigger className={cn("h-8", compact ? "w-44" : "w-52")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="custom">自定义</SelectItem>
            <SelectItem value="economical">Economical (省成本)</SelectItem>
            <SelectItem value="high_quality">High-quality (高质量)</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {!compact && (
        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              ctx.reset()
              toast.message('已重置为默认管线')
            }}
          >
            重置
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={importPipelineJson}>
            导入 JSON
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={exportPipelineJson}>
            导出 JSON
          </Button>
        </div>
      )}

      <div className={cn("grid gap-3", compact ? "gap-3" : "gap-4")}>
        {optionGroups.map((group) => {
          const Icon = group.icon
          return (
            <div
              key={group.title}
              className={cn(
                "rounded-xl border border-border bg-card overflow-hidden shadow-sm transition-shadow hover:shadow-md",
                !enabled && "opacity-60 grayscale-[0.5] pointer-events-none"
              )}
            >
              <div className="flex items-center gap-2 px-3 py-2 bg-muted/50 border-b border-border">
                <div className={cn("p-1 rounded-md", group.bgColor)}>
                  <Icon className={cn("h-3.5 w-3.5", group.color)} />
                </div>
                <span className={cn("font-semibold text-foreground/80", titleClasses)}>{group.title}</span>
              </div>

              <div className="p-3 space-y-3">
                {group.items.map((item) => {
                  const depends = item.dependsOn === 'kg_enabled'
                  const disabled = !enabled || (depends && !kgEnabled)
                  const checked = !!options[item.key as keyof typeof options]
                  return (
                    <div key={item.key} className="flex items-center justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className={cn("font-medium text-foreground/80 truncate", titleClasses)}>
                          {item.label}
                        </div>
                        <p className={cn("text-muted-foreground truncate", descClasses)}>
                          {item.hint}
                        </p>
                      </div>
                      <Switch
                        checked={checked}
                        onCheckedChange={(value) => handleChecked(item.key as keyof typeof options, value)}
                        disabled={disabled}
                        className="scale-90 origin-right"
                      />
                    </div>
                  )
                })}
              </div>

              {group.title === '数据治理' && (
                <div className="border-t border-border">
                  <details className="group/details">
                    <summary className={cn("flex items-center justify-between cursor-pointer select-none px-3 py-2 text-muted-foreground hover:text-foreground/80 hover:bg-muted transition-colors", descClasses)}>
                      <span>高级治理参数</span>
                      <ChevronDown className="h-3 w-3 transition-transform group-open/details:rotate-180" />
                    </summary>
                    <div className="p-3 pt-0 space-y-4 bg-muted/30">
                      <div className="space-y-2 pt-2">
                        <div className={cn("text-xs font-semibold text-foreground/70", compact && "text-[10px]")}>
                          治理清洗
                        </div>
                        <div className="space-y-3">
                          {governanceToggles.map((item) => {
                            const checked = !!options[item.key as keyof typeof options]
                            const dependsOn = (item as any).dependsOn as (keyof typeof options) | undefined
                            const disabled = governanceDisabled || (dependsOn ? !options[dependsOn] : false)
                            return (
                              <div key={item.key} className="flex items-center justify-between gap-3">
                                <div className="flex-1 min-w-0">
                                  <div className={cn("font-medium text-foreground/80 truncate", titleClasses)}>
                                    {item.label}
                                  </div>
                                  <p className={cn("text-muted-foreground truncate", descClasses)}>
                                    {item.hint}
                                  </p>
                                </div>
                                <Switch
                                  checked={checked}
                                  onCheckedChange={(value) => handleChecked(item.key as keyof typeof options, value)}
                                  disabled={disabled}
                                  className="scale-75 origin-right"
                                />
                              </div>
                            )
                          })}
                        </div>
                      </div>

                      {/* Image removal */}
                      <div className="space-y-1.5">
                        <label className={cn("text-xs font-medium text-muted-foreground block", compact && "text-[10px]")}>图片处理</label>
                        <Select
                          value={(options.governance_remove_images as string) || 'none'}
                          onValueChange={(v) => updateOption('governance_remove_images', v as any)}
                          disabled={governanceDisabled}
                        >
                          <SelectTrigger className={cn("h-8 text-xs bg-card", compact && "h-7")}>
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
                            <div className={cn("font-medium text-foreground/80 truncate", titleClasses)}>
                              去追踪参数
                            </div>
                            <p className={cn("text-muted-foreground truncate", descClasses)}>
                              移除 utm_* / gclid / fbclid 等
                            </p>
                          </div>
                          <Switch
                            checked={!!options.governance_normalize_urls_strip_tracking}
                            onCheckedChange={(value) => handleChecked('governance_normalize_urls_strip_tracking' as any, value)}
                            disabled={governanceDisabled}
                            className="scale-75 origin-right"
                          />
                        </div>
                      )}

                      {/* PII settings */}
                      {!governanceDisabled && options.governance_pii_anonymize && (
                        <div className="space-y-1.5">
                          <label className={cn("text-xs font-medium text-muted-foreground block", compact && "text-[10px]")}>隐私脱敏配置</label>
                          <div className="grid grid-cols-2 gap-2">
                            <Select
                              value={(options.governance_pii_mode as string) || 'mask'}
                              onValueChange={(v) => updateOption('governance_pii_mode', v as any)}
                              disabled={governanceDisabled}
                            >
                              <SelectTrigger className={cn("h-8 text-xs bg-card", compact && "h-7")}>
                                <SelectValue placeholder="模式" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="mask">掩码替换</SelectItem>
                                <SelectItem value="token">占位符</SelectItem>
                              </SelectContent>
                            </Select>
                            <Input
                              value={options.governance_pii_mask || ''}
                              disabled={governanceDisabled || (options.governance_pii_mode as string) === 'token'}
                              onChange={(e) => updateOption('governance_pii_mask', e.currentTarget.value as any)}
                              placeholder="[REDACTED]"
                              className={cn("h-8 text-xs bg-card", compact && "h-7")}
                            />
                          </div>
                        </div>
                      )}

                      {/* Secrets settings */}
                      {!governanceDisabled && options.governance_secrets_redact && (
                        <div className="space-y-1.5">
                          <label className={cn("text-xs font-medium text-muted-foreground block", compact && "text-[10px]")}>密钥脱敏配置</label>
                          <div className="grid grid-cols-2 gap-2">
                            <Select
                              value={(options.governance_secrets_mode as string) || 'mask'}
                              onValueChange={(v) => updateOption('governance_secrets_mode', v as any)}
                              disabled={governanceDisabled}
                            >
                              <SelectTrigger className={cn("h-8 text-xs bg-card", compact && "h-7")}>
                                <SelectValue placeholder="模式" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="mask">掩码替换</SelectItem>
                                <SelectItem value="token">占位符</SelectItem>
                              </SelectContent>
                            </Select>
                            <Input
                              value={options.governance_secrets_mask || ''}
                              disabled={governanceDisabled || (options.governance_secrets_mode as string) === 'token'}
                              onChange={(e) => updateOption('governance_secrets_mask', e.currentTarget.value as any)}
                              placeholder="[SECRET]"
                              className={cn("h-8 text-xs bg-card", compact && "h-7")}
                            />
                          </div>
                        </div>
                      )}

                      {/* Keyword settings */}
                      {!governanceDisabled && options.governance_extract_keywords && (
                        <div className="space-y-2">
                          <label className={cn("text-xs font-medium text-muted-foreground block", compact && "text-[10px]")}>关键词抽取配置</label>
                          <div className="grid grid-cols-2 gap-2">
                            <Select
                              value={(options.governance_keywords_provider as string) || 'auto'}
                              onValueChange={(v) => updateOption('governance_keywords_provider', v as any)}
                              disabled={governanceDisabled}
                            >
                              <SelectTrigger className={cn("h-8 text-xs bg-card", compact && "h-7")}>
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
                              onChange={(e) => handleNumberChange('governance_keywords_top_k' as any, e.currentTarget.valueAsNumber)}
                              className={cn("h-8 text-xs bg-card", compact && "h-7")}
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
                            onChange={(e) => handleNumberChange('governance_keywords_max_chars' as any, e.currentTarget.valueAsNumber)}
                            className={cn("h-8 text-xs bg-card", compact && "h-7")}
                            placeholder="关键词抽取最大字符"
                          />
                        </div>
                      )}

                      {/* HTML XPath */}
                      <div className="space-y-1.5">
                        <div className="flex justify-between">
                           <label className={cn("text-xs font-medium text-muted-foreground", compact && "text-[10px]")}>HTML 提取 (XPath)</label>
                        </div>
                        <Input
                          value={options.governance_html_xpath || ''}
                          disabled={governanceDisabled}
                          onChange={(e) => updateOption('governance_html_xpath', e.currentTarget.value as any)}
                          placeholder="//article | //main"
                          className={cn("h-8 text-xs bg-card font-mono", compact && "h-7")}
                        />
                      </div>

                      <div className="grid gap-3 pt-1">
                        {governanceNumbers.map((item) => {
                          const value = options[item.key as keyof typeof options]
                          const dependsOn = (item as any).dependsOn as (keyof typeof options) | undefined
                          const shouldHide =
                            (item.key === 'governance_drop_outline_min_content_chars' || item.key === 'governance_drop_outline_max_heading_ratio') &&
                            !options.governance_drop_outline_only
                          const shouldHideLowDensity = item.key === 'governance_drop_low_density_threshold' && !options.governance_drop_low_density
                          const shouldHideDepends = dependsOn ? !options[dependsOn] : false
                          if (shouldHide || shouldHideLowDensity || shouldHideDepends) return null
                          return (
                            <label key={item.key} className="flex items-center justify-between gap-2">
                              <span className={cn("text-xs text-muted-foreground truncate flex-1", compact && "text-[10px]")} title={item.hint}>{item.label}</span>
                              <Input
                                type="number"
                                value={typeof value === 'number' ? value : ''}
                                min={item.min}
                                max={item.max}
                                step={item.step}
                                disabled={governanceDisabled}
                                onChange={(e) => handleNumberChange(item.key as keyof typeof options, e.currentTarget.valueAsNumber)}
                                className={cn(
                                  "h-7 w-16 text-right text-xs bg-card px-1",
                                  compact && "h-6"
                                )}
                              />
                            </label>
                          )
                        })}
                      </div>

                      <div className="pt-2 border-t border-border/60 space-y-2">
                        <div className={cn("text-xs font-semibold text-foreground/70", compact && "text-[10px]")}>
                          解析与去重
                        </div>
                        <div className="space-y-3">
                          {pipelineToggles.map((item) => {
                            const checked = !!options[item.key as keyof typeof options]
                            return (
                              <div key={item.key} className="flex items-center justify-between gap-3">
                                <div className="flex-1 min-w-0">
                                  <div className={cn("font-medium text-foreground/80 truncate", titleClasses)}>
                                    {item.label}
                                  </div>
                                  <p className={cn("text-muted-foreground truncate", descClasses)}>
                                    {item.hint}
                                  </p>
                                </div>
                                <Switch
                                  checked={checked}
                                  onCheckedChange={(value) => handleChecked(item.key as keyof typeof options, value)}
                                  disabled={pipelineDisabled}
                                  className="scale-75 origin-right"
                                />
                              </div>
                            )
                          })}
                        </div>

                        <div className="grid gap-3 pt-1">
                          {pipelineNumbers.map((item) => {
                            const value = options[item.key as keyof typeof options]
                            const dependsOn = (item as any).dependsOn as (keyof typeof options) | undefined
                            const shouldHide = dependsOn ? !options[dependsOn] : false
                            if (shouldHide) return null
                            return (
                              <label key={item.key} className="flex items-center justify-between gap-2">
                                <span className={cn("text-xs text-muted-foreground truncate flex-1", compact && "text-[10px]")} title={item.hint}>{item.label}</span>
                                <Input
                                  type="number"
                                  value={typeof value === 'number' ? value : ''}
                                  min={(item as any).min}
                                  max={(item as any).max}
                                  step={(item as any).step}
                                  disabled={pipelineDisabled}
                                  onChange={(e) => handleNumberChange(item.key as keyof typeof options, e.currentTarget.valueAsNumber)}
                                  className={cn(
                                    "h-7 w-16 text-right text-xs bg-card px-1",
                                    compact && "h-6"
                                  )}
                                />
                              </label>
                            )
                          })}
                        </div>

                        <div className="pt-2 border-t border-border/60 space-y-2">
                          <div className={cn("text-xs font-semibold text-foreground/70", compact && "text-[10px]")}>
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
                            className={cn(
                              "min-h-[84px] text-[11px] font-mono bg-card",
                              compact && "min-h-[70px] text-[10px]"
                            )}
                            placeholder='例如：{ "child_ratio": 0.25, "min_child_size": 300 }'
                          />
                          {chunkStrategyParamsError ? (
                            <div className={cn("text-[11px] text-warning bg-warning/10 border border-warning/25 rounded-lg px-2 py-1", compact && "text-[10px]")}>
                              {chunkStrategyParamsError}
                            </div>
                          ) : (
                            <div className={cn("text-[10px] text-muted-foreground leading-relaxed", compact && "text-[9px]")}>
                              仅允许小型 JSON 对象（primitive values），后端会做同样的安全校验；显式参数将覆盖数据集/默认值。
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </details>
                </div>
              )}

              {group.title === '知识图谱' && !kgEnabled && (
                <div className={cn("px-3 py-2 bg-muted border-t border-border flex items-center gap-2 text-muted-foreground italic", descClasses)}>
                  <Sparkles className="h-3 w-3" />
                  需先开启 KG 抽取才能配置索引
                </div>
              )}
            </div>
          )
        })}
      </div>

      {enabled && (
        <div className={cn("flex items-center justify-center gap-1.5 text-muted-foreground mt-2", descClasses)}>
          <CheckCircle2 className="h-3 w-3" />
          <span>自定义配置已生效</span>
        </div>
      )}
    </div>
  )
}
