'use client'

import { useMemo } from 'react'
import { CheckCircle2, Layers, Network, ShieldCheck, Sparkles } from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'

type PipelineOptionsPanelProps = {
  className?: string
  compact?: boolean
}

export function PipelineOptionsPanel({ className, compact }: PipelineOptionsPanelProps) {
  const { enabled, options, setEnabled, updateOption } = usePipelineOptions()
  const kgEnabled = !!options.kg_enabled
  const governanceEnabled = !!options.governance_enabled
  const governanceDisabled = !enabled || !governanceEnabled

  const titleClasses = compact ? 'text-xs' : 'text-sm'
  const descClasses = compact ? 'text-[10px]' : 'text-xs'

  const optionGroups = useMemo(() => ([
    {
      title: '治理',
      icon: ShieldCheck,
      items: [
        {
          key: 'governance_enabled',
          label: '数据治理清洗',
          hint: '解析后统一规范化 Markdown',
        },
      ],
    },
    {
      title: '索引',
      icon: Layers,
      items: [
        {
          key: 'chunk_vector_enabled',
          label: 'Chunk 向量索引',
          hint: '写入向量库以支持语义检索',
        },
        {
          key: 'bm25_index_enabled',
          label: 'BM25 全文索引',
          hint: '启用关键词检索与混合召回',
        },
      ],
    },
    {
      title: '知识图谱',
      icon: Network,
      items: [
        {
          key: 'kg_enabled',
          label: 'KG 事件抽取',
          hint: '抽取事件/实体用于知识图谱检索',
        },
        {
          key: 'event_vector_enabled',
          label: '事件向量索引',
          hint: '事件嵌入写入向量库',
          dependsOn: 'kg_enabled',
        },
        {
          key: 'entity_vector_enabled',
          label: '实体向量索引',
          hint: '实体嵌入写入向量库',
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
    <div className={cn("space-y-4", className)}>
      <div className="flex items-start gap-3">
        <Checkbox
          checked={enabled}
          onCheckedChange={(value) => setEnabled(value === true)}
          className="mt-1"
        />
        <div>
          <div className={cn("font-semibold text-gray-900", titleClasses)}>
            启用自定义管线
          </div>
          <p className={cn("text-gray-500 leading-relaxed", descClasses)}>
            关闭时使用后端默认配置，仅对新上传文档生效
          </p>
        </div>
      </div>

      <div className={cn("grid gap-4", compact ? "gap-3" : "gap-4")}>
        {optionGroups.map((group) => {
          const Icon = group.icon
          return (
            <div
              key={group.title}
              className={cn(
                "rounded-xl border border-gray-100 bg-gray-50/40 px-4 py-3",
                compact && "px-3 py-2"
              )}
            >
              <div className="flex items-center gap-2 mb-2 text-gray-700">
                <Icon className={cn("h-4 w-4", compact && "h-3.5 w-3.5")} />
                <span className={cn("font-semibold", titleClasses)}>{group.title}</span>
              </div>

              <div className="space-y-2">
                {group.items.map((item) => {
                  const depends = item.dependsOn === 'kg_enabled'
                  const disabled = !enabled || (depends && !kgEnabled)
                  const checked = !!options[item.key as keyof typeof options]
                  return (
                    <label
                      key={item.key}
                      className={cn(
                        "flex items-start gap-2 rounded-lg border border-transparent px-2 py-2 transition-colors",
                        !disabled && "hover:border-gray-200 hover:bg-white",
                        disabled && "opacity-60"
                      )}
                    >
                      <Checkbox
                        checked={checked}
                        onCheckedChange={(value) => handleChecked(item.key as keyof typeof options, value)}
                        disabled={disabled}
                        className="mt-0.5"
                      />
                      <div>
                        <div className={cn("font-medium text-gray-800", titleClasses)}>
                          {item.label}
                        </div>
                        <p className={cn("text-gray-500", descClasses)}>
                          {item.hint}
                        </p>
                      </div>
                    </label>
                  )
                })}
              </div>

              {group.title === '治理' && (
                <details className="mt-2" open={!compact}>
                  <summary className={cn("cursor-pointer select-none text-gray-500", descClasses)}>
                    高级治理
                  </summary>
                  <div className={cn("mt-3 space-y-3", compact && "space-y-2")}>
                    <div className="grid gap-2">
                      {governanceToggles.map((item) => {
                        const checked = !!options[item.key as keyof typeof options]
                        return (
                          <label
                            key={item.key}
                            className={cn(
                              "flex items-start gap-2 rounded-lg border border-transparent px-2 py-2 transition-colors",
                              !governanceDisabled && "hover:border-gray-200 hover:bg-white",
                              governanceDisabled && "opacity-60"
                            )}
                          >
                            <Checkbox
                              checked={checked}
                              onCheckedChange={(value) => handleChecked(item.key as keyof typeof options, value)}
                              disabled={governanceDisabled}
                              className="mt-0.5"
                            />
                            <div>
                              <div className={cn("font-medium text-gray-800", titleClasses)}>
                                {item.label}
                              </div>
                              <p className={cn("text-gray-500", descClasses)}>
                                {item.hint}
                              </p>
                            </div>
                          </label>
                        )
                      })}
                    </div>

                    {/* Image removal */}
                    <div className="grid gap-2">
                      <div className={cn("text-xs text-gray-600", compact && "text-[10px]")}>图片处理</div>
                      <Select
                        value={(options.governance_remove_images as string) || 'none'}
                        onValueChange={(v) => updateOption('governance_remove_images', v as any)}
                        disabled={governanceDisabled}
                      >
                        <SelectTrigger className={cn("h-9 text-xs", compact && "h-8")}>
                          <SelectValue placeholder="选择图片处理方式" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">保留图片</SelectItem>
                          <SelectItem value="decorative">删除装饰图（logo/二维码）</SelectItem>
                          <SelectItem value="all">删除全部图片</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    {/* PII settings */}
                    {!governanceDisabled && options.governance_pii_anonymize && (
                      <div className="grid gap-2">
                        <div className={cn("text-xs text-gray-600", compact && "text-[10px]")}>隐私脱敏</div>
                        <div className="grid grid-cols-2 gap-2">
                          <Select
                            value={(options.governance_pii_mode as string) || 'mask'}
                            onValueChange={(v) => updateOption('governance_pii_mode', v as any)}
                            disabled={governanceDisabled}
                          >
                            <SelectTrigger className={cn("h-9 text-xs", compact && "h-8")}>
                              <SelectValue placeholder="脱敏模式" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="mask">固定替换</SelectItem>
                              <SelectItem value="token">生成占位符</SelectItem>
                            </SelectContent>
                          </Select>
                          <Input
                            value={options.governance_pii_mask || ''}
                            disabled={governanceDisabled || (options.governance_pii_mode as string) === 'token'}
                            onChange={(e) => updateOption('governance_pii_mask', e.currentTarget.value as any)}
                            placeholder="[REDACTED]"
                            className={cn("h-9 text-xs", compact && "h-8")}
                          />
                        </div>
                      </div>
                    )}

                    {/* HTML XPath */}
                    <div className="grid gap-2">
                      <div className={cn("text-xs text-gray-600", compact && "text-[10px]")}>HTML XPath（可选）</div>
                      <Input
                        value={options.governance_html_xpath || ''}
                        disabled={governanceDisabled}
                        onChange={(e) => updateOption('governance_html_xpath', e.currentTarget.value as any)}
                        placeholder="//article | //main | //body"
                        className={cn("h-9 text-xs", compact && "h-8")}
                      />
                      <div className={cn("text-[10px] text-gray-400", compact && "text-[9px]")}>
                        仅对 HTML/HTM 文件或输入格式为 HTML 时生效
                      </div>
                    </div>

                    <div className={cn("grid gap-2", compact ? "gap-2" : "gap-3")}>
                      {governanceNumbers.map((item) => {
                        const value = options[item.key as keyof typeof options]
                        const shouldHide =
                          (item.key === 'governance_drop_outline_min_content_chars' || item.key === 'governance_drop_outline_max_heading_ratio') &&
                          !options.governance_drop_outline_only
                        const shouldHideLowDensity = item.key === 'governance_drop_low_density_threshold' && !options.governance_drop_low_density
                        if (shouldHide || shouldHideLowDensity) return null
                        return (
                          <label key={item.key} className="flex flex-col gap-1">
                            <div className="flex items-center justify-between text-xs text-gray-600">
                              <span>{item.label}</span>
                              <span className="text-[10px] text-gray-400">{item.hint}</span>
                            </div>
                            <Input
                              type="number"
                              value={typeof value === 'number' ? value : ''}
                              min={item.min}
                              max={item.max}
                              step={item.step}
                              disabled={governanceDisabled}
                              onChange={(e) => handleNumberChange(item.key as keyof typeof options, e.currentTarget.valueAsNumber)}
                              className={cn(
                                "h-9 text-xs",
                                compact && "h-8"
                              )}
                            />
                          </label>
                        )
                      })}
                    </div>
                  </div>
                </details>
              )}

              {group.title === '知识图谱' && !kgEnabled && (
                <div className={cn("mt-2 flex items-center gap-2 text-gray-400", descClasses)}>
                  <Sparkles className="h-3 w-3" />
                  事件/实体索引需先开启 KG
                </div>
              )}
            </div>
          )
        })}
      </div>

      {enabled && (
        <div className={cn("flex items-center gap-2 text-gray-400", descClasses)}>
          <CheckCircle2 className="h-3 w-3" />
          启用后将覆盖默认索引与治理行为
        </div>
      )}
    </div>
  )
}
