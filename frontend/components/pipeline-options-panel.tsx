'use client'

import { useMemo } from 'react'
import { CheckCircle2, Layers, Network, ShieldCheck, Sparkles } from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/utils'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'

type PipelineOptionsPanelProps = {
  className?: string
  compact?: boolean
}

export function PipelineOptionsPanel({ className, compact }: PipelineOptionsPanelProps) {
  const { enabled, options, setEnabled, updateOption } = usePipelineOptions()
  const sagEnabled = !!options.sag_enabled

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
          key: 'sag_enabled',
          label: 'SAG 事件抽取',
          hint: '抽取事件/实体用于 KG 检索',
        },
        {
          key: 'event_vector_enabled',
          label: '事件向量索引',
          hint: '事件嵌入写入向量库',
          dependsOn: 'sag_enabled',
        },
        {
          key: 'entity_vector_enabled',
          label: '实体向量索引',
          hint: '实体嵌入写入向量库',
          dependsOn: 'sag_enabled',
        },
      ],
    },
  ]), [])

  const handleChecked = (key: keyof typeof options, value: boolean | 'indeterminate') => {
    updateOption(key, value === true)
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
                  const depends = item.dependsOn === 'sag_enabled'
                  const disabled = !enabled || (depends && !sagEnabled)
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

              {group.title === '知识图谱' && !sagEnabled && (
                <div className={cn("mt-2 flex items-center gap-2 text-gray-400", descClasses)}>
                  <Sparkles className="h-3 w-3" />
                  事件/实体索引需先开启 SAG
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
