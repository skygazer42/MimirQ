'use client'

import { useMemo } from 'react'
import { CheckCircle2, Layers, Network, ShieldCheck, Sparkles, ChevronDown } from 'lucide-react'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
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

  const titleClasses = compact ? 'text-xs' : 'text-sm'
  const descClasses = compact ? 'text-[10px]' : 'text-xs'

  const optionGroups = useMemo(() => ([
    {
      title: '数据治理',
      icon: ShieldCheck,
      color: 'text-indigo-600',
      bgColor: 'bg-indigo-50',
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
      color: 'text-sky-600',
      bgColor: 'bg-sky-50',
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
      title: '知识图谱',
      icon: Network,
      color: 'text-purple-600',
      bgColor: 'bg-purple-50',
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
      key: 'governance_pii_anonymize',
      label: '匿名化隐私信息',
      hint: '邮箱/电话/身份证/卡号等脱敏',
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
  ] as const

  const governanceNumbers = [
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

  const handleChecked = (key: keyof typeof options, value: boolean | 'indeterminate') => {
    updateOption(key, value === true)
  }

  const handleNumberChange = <K extends keyof typeof options>(key: K, value: number) => {
    if (!Number.isFinite(value)) return
    updateOption(key, value as (typeof options)[K])
  }

  return (
    <div className={cn("space-y-4 font-sans", className)}>
      {!props.hideEnabledToggle && (
        <div className="flex items-center justify-between p-3 rounded-xl bg-slate-50 border border-slate-200">
          <div>
            <div className={cn("font-semibold text-slate-900", titleClasses)}>
              自定义管线
            </div>
            <p className={cn("text-slate-500", descClasses)}>
              开启后可配置详细的处理流程
            </p>
          </div>
          <Switch
            checked={enabled}
            onCheckedChange={(value) => setEnabled(value === true)}
          />
        </div>
      )}

      <div className={cn("grid gap-3", compact ? "gap-3" : "gap-4")}>
        {optionGroups.map((group) => {
          const Icon = group.icon
          return (
            <div
              key={group.title}
              className={cn(
                "rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm transition-shadow hover:shadow-md",
                !enabled && "opacity-60 grayscale-[0.5] pointer-events-none"
              )}
            >
              <div className="flex items-center gap-2 px-3 py-2 bg-slate-50/50 border-b border-slate-100">
                <div className={cn("p-1 rounded-md", group.bgColor)}>
                  <Icon className={cn("h-3.5 w-3.5", group.color)} />
                </div>
                <span className={cn("font-semibold text-slate-700", titleClasses)}>{group.title}</span>
              </div>

              <div className="p-3 space-y-3">
                {group.items.map((item) => {
                  const depends = item.dependsOn === 'kg_enabled'
                  const disabled = !enabled || (depends && !kgEnabled)
                  const checked = !!options[item.key as keyof typeof options]
                  return (
                    <div key={item.key} className="flex items-center justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className={cn("font-medium text-slate-700 truncate", titleClasses)}>
                          {item.label}
                        </div>
                        <p className={cn("text-slate-400 truncate", descClasses)}>
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
                <div className="border-t border-slate-100">
                  <details className="group/details">
                    <summary className={cn("flex items-center justify-between cursor-pointer select-none px-3 py-2 text-slate-500 hover:text-slate-700 hover:bg-slate-50 transition-colors", descClasses)}>
                      <span>高级治理参数</span>
                      <ChevronDown className="h-3 w-3 transition-transform group-open/details:rotate-180" />
                    </summary>
                    <div className="p-3 pt-0 space-y-4 bg-slate-50/30">
                      <div className="space-y-3 pt-2">
                        {governanceToggles.map((item) => {
                          const checked = !!options[item.key as keyof typeof options]
                          return (
                            <div key={item.key} className="flex items-center justify-between gap-3">
                              <div className="flex-1 min-w-0">
                                <div className={cn("font-medium text-slate-700 truncate", titleClasses)}>
                                  {item.label}
                                </div>
                                <p className={cn("text-slate-400 truncate", descClasses)}>
                                  {item.hint}
                                </p>
                              </div>
                              <Switch
                                checked={checked}
                                onCheckedChange={(value) => handleChecked(item.key as keyof typeof options, value)}
                                disabled={governanceDisabled}
                                className="scale-75 origin-right"
                              />
                            </div>
                          )
                        })}
                      </div>

                      {/* Image removal */}
                      <div className="space-y-1.5">
                        <label className={cn("text-xs font-medium text-slate-600 block", compact && "text-[10px]")}>图片处理</label>
                        <Select
                          value={(options.governance_remove_images as string) || 'none'}
                          onValueChange={(v) => updateOption('governance_remove_images', v as any)}
                          disabled={governanceDisabled}
                        >
                          <SelectTrigger className={cn("h-8 text-xs bg-white", compact && "h-7")}>
                            <SelectValue placeholder="选择方式" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">保留图片</SelectItem>
                            <SelectItem value="decorative">删除装饰图</SelectItem>
                            <SelectItem value="all">删除全部图片</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>

                      {/* PII settings */}
                      {!governanceDisabled && options.governance_pii_anonymize && (
                        <div className="space-y-1.5">
                          <label className={cn("text-xs font-medium text-slate-600 block", compact && "text-[10px]")}>隐私脱敏配置</label>
                          <div className="grid grid-cols-2 gap-2">
                            <Select
                              value={(options.governance_pii_mode as string) || 'mask'}
                              onValueChange={(v) => updateOption('governance_pii_mode', v as any)}
                              disabled={governanceDisabled}
                            >
                              <SelectTrigger className={cn("h-8 text-xs bg-white", compact && "h-7")}>
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
                              className={cn("h-8 text-xs bg-white", compact && "h-7")}
                            />
                          </div>
                        </div>
                      )}

                      {/* HTML XPath */}
                      <div className="space-y-1.5">
                        <div className="flex justify-between">
                           <label className={cn("text-xs font-medium text-slate-600", compact && "text-[10px]")}>HTML 提取 (XPath)</label>
                        </div>
                        <Input
                          value={options.governance_html_xpath || ''}
                          disabled={governanceDisabled}
                          onChange={(e) => updateOption('governance_html_xpath', e.currentTarget.value as any)}
                          placeholder="//article | //main"
                          className={cn("h-8 text-xs bg-white font-mono", compact && "h-7")}
                        />
                      </div>

                      <div className="grid gap-3 pt-1">
                        {governanceNumbers.map((item) => {
                          const value = options[item.key as keyof typeof options]
                          const shouldHide =
                            (item.key === 'governance_drop_outline_min_content_chars' || item.key === 'governance_drop_outline_max_heading_ratio') &&
                            !options.governance_drop_outline_only
                          const shouldHideLowDensity = item.key === 'governance_drop_low_density_threshold' && !options.governance_drop_low_density
                          if (shouldHide || shouldHideLowDensity) return null
                          return (
                            <label key={item.key} className="flex items-center justify-between gap-2">
                              <span className={cn("text-xs text-slate-600 truncate flex-1", compact && "text-[10px]")} title={item.hint}>{item.label}</span>
                              <Input
                                type="number"
                                value={typeof value === 'number' ? value : ''}
                                min={item.min}
                                max={item.max}
                                step={item.step}
                                disabled={governanceDisabled}
                                onChange={(e) => handleNumberChange(item.key as keyof typeof options, e.currentTarget.valueAsNumber)}
                                className={cn(
                                  "h-7 w-16 text-right text-xs bg-white px-1",
                                  compact && "h-6"
                                )}
                              />
                            </label>
                          )
                        })}
                      </div>
                    </div>
                  </details>
                </div>
              )}

              {group.title === '知识图谱' && !kgEnabled && (
                <div className={cn("px-3 py-2 bg-slate-50 border-t border-slate-100 flex items-center gap-2 text-slate-400 italic", descClasses)}>
                  <Sparkles className="h-3 w-3" />
                  需先开启 KG 抽取才能配置索引
                </div>
              )}
            </div>
          )
        })}
      </div>

      {enabled && (
        <div className={cn("flex items-center justify-center gap-1.5 text-slate-400 mt-2", descClasses)}>
          <CheckCircle2 className="h-3 w-3" />
          <span>自定义配置已生效</span>
        </div>
      )}
    </div>
  )
}
