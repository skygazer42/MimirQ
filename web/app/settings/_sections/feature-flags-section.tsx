'use client'

import { cn } from '@/lib/utils'
import type { FeatureFlags } from '@/lib/api'
import {
  AlertCircle,
  CloudCog,
  FileCode,
  FileSearch,
  LayoutGrid,
  Network,
  ScanLine,
  Sparkles,
  Wand2,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { systemPageTokens } from '@/components/ui/system-page-tokens'

type FeatureFlagDescriptor = {
  key: keyof FeatureFlags
  name: string
  description: string
  icon: LucideIcon
  color: 'teal' | 'orange' | 'cyan' | 'green'
  dependencies: string[]
}

const FEATURE_FLAGS_CONFIG: FeatureFlagDescriptor[] = [
  {
    key: 'kg_enabled',
    name: 'KG 知识抽取',
    description: '启用知识图谱抽取，自动抽取文档中的实体和事件',
    icon: Sparkles,
    color: 'teal',
    dependencies: ['向量数据库（Milvus）', '大语言模型（LLM）'],
  },
  {
    key: 'deepdoc_enabled',
    name: 'DeepDoc 结构化解析',
    description: '启用视觉 + OCR 解析能力，适合扫描件/图文混排 PDF（自动选择时生效）',
    icon: ScanLine,
    color: 'orange',
    dependencies: [],
  },
  {
    key: 'docling_enabled',
    name: 'Docling 结构化解析',
    description: '启用 Docling 解析，对版面/表格结构抽取更友好（自动选择时生效）',
    icon: FileSearch,
    color: 'cyan',
    dependencies: [],
  },
  {
    key: 'etl4llm_enabled',
    name: 'ETL4LLM 版面解析',
    description: '启用 ETL4LLM 版面/表格/图片解析（需自建服务，自动选择时生效）',
    icon: LayoutGrid,
    color: 'green',
    dependencies: ['ETL4LLM 服务地址（API URL）'],
  },
  {
    key: 'marker_enabled',
    name: 'Marker 启发式解析',
    description: '启用 Marker 启发式 PDF→Markdown 解析服务（可在解析器下拉中选择）',
    icon: LayoutGrid,
    color: 'green',
    dependencies: ['Marker 服务地址（API URL）'],
  },
  {
    key: 'paddle_vl_enabled',
    name: 'PaddleOCR-VL 外部解析',
    description: '启用 PaddleOCR-VL 外部 OCR/版面解析服务（适合扫描件 PDF，可在解析器下拉中选择）',
    icon: ScanLine,
    color: 'orange',
    dependencies: ['PaddleOCR-VL 服务地址（API URL）'],
  },
  {
    key: 'textin_enabled',
    name: 'TextIn xParse 外部解析',
    description: '启用 TextIn 文档解析 API（可用于 PDF/Office/图片等文档转 Markdown）',
    icon: CloudCog,
    color: 'cyan',
    dependencies: ['TextIn API 地址', 'TextIn APP ID', 'TextIn Secret Code'],
  },
  {
    key: 'markitdown_enabled',
    name: 'MarkItDown 文档解析',
    description: '启用多格式转 Markdown（Office/表格/PDF），自动选择与解析工作台会使用',
    icon: FileCode,
    color: 'teal',
    dependencies: [],
  },
  {
    key: 'llama_index_enabled',
    name: 'LlamaIndex 分块',
    description: '启用 LlamaIndex 高级分块策略',
    icon: Network,
    color: 'orange',
    dependencies: [],
  },
  {
    key: 'mineru_enabled',
    name: 'MinerU 在线接口（API）',
    description: '使用 MinerU 在线接口（API）进行文档解析',
    icon: CloudCog,
    color: 'cyan',
    dependencies: ['MinerU API 令牌（API Token）'],
  },
  {
    key: 'magicpdf_enabled',
    name: 'MagicPDF 本地解析',
    description: '启用 magic-pdf 本地高级解析后端（可在解析器下拉中选择）',
    icon: Wand2,
    color: 'teal',
    dependencies: ['magic-pdf'],
  },
]

function getColorClasses(color: FeatureFlagDescriptor['color']) {
  const styles = {
    primary: {
      bg: 'bg-blue-50/35',
      border: 'border-blue-200/75',
      text: 'text-blue-600',
      iconBg: 'bg-blue-100/65',
    },
    info: {
      bg: 'bg-cyan-50/35',
      border: 'border-cyan-200/75',
      text: 'text-cyan-600',
      iconBg: 'bg-cyan-100/65',
    },
    success: {
      bg: 'bg-emerald-50/35',
      border: 'border-emerald-200/75',
      text: 'text-emerald-600',
      iconBg: 'bg-emerald-100/65',
    },
    warning: {
      bg: 'bg-orange-50/35',
      border: 'border-orange-200/75',
      text: 'text-orange-600',
      iconBg: 'bg-orange-100/65',
    },
  }

  const key =
    color === 'green' ? 'success' : color === 'orange' ? 'warning' : color === 'cyan' ? 'primary' : 'info'

  return styles[key]
}

type FeatureFlagsSectionProps = {
  editedFeatureFlags?: Partial<FeatureFlags>
  getFeatureValue: (key: keyof FeatureFlags) => boolean
  toggleFeature: (key: keyof FeatureFlags) => void
}

export function FeatureFlagsSection({
  editedFeatureFlags,
  getFeatureValue,
  toggleFeature,
}: Readonly<FeatureFlagsSectionProps>) {
  return (
    <section className="rounded-[16px] border border-slate-200/75 bg-white p-3.5 shadow-sm">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-[13px] font-medium text-slate-950">
            <Zap className="h-3.5 w-3.5 text-orange-500" />
            功能开关
          </h2>
          <p className="mt-0.5 text-[11px] leading-4 text-slate-500">
            按需启用各项能力模块，依赖项会在下方标签提示。
          </p>
        </div>
        <div className="inline-flex items-center gap-1.5 rounded-full border border-orange-200 bg-orange-50/70 px-2.5 py-1 text-[11px] font-medium text-orange-600">
          <AlertCircle className="h-3 w-3" />
          <span>更改后需重启后端生效</span>
        </div>
      </div>

      <div className="mt-3.5 grid grid-cols-1 gap-2 xl:grid-cols-2">
        {FEATURE_FLAGS_CONFIG.map((feature) => {
          const Icon = feature.icon
          const colors = getColorClasses(feature.color)
          const isEnabled = getFeatureValue(feature.key)
          const isEdited = Boolean(editedFeatureFlags && feature.key in editedFeatureFlags)

          return (
            <button
              type="button"
              key={feature.key}
              className={cn(
                'group relative w-full rounded-[13px] border px-3 py-2 text-left transition-[border-color,background-color,box-shadow] duration-150 focus-ring motion-reduce:transition-none',
                isEnabled ? `${colors.border} ${colors.bg} shadow-[inset_0_0_0_1px_rgba(255,255,255,0.55)]` : 'border-slate-200 bg-white hover:border-blue-100 hover:bg-slate-50/65',
                isEdited && 'ring-2 ring-blue-400/70 ring-offset-1'
              )}
              aria-pressed={isEnabled}
              onClick={() => toggleFeature(feature.key)}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2.5">
                  <div
                    className={cn(
                      'mt-0.5 flex size-[23px] shrink-0 items-center justify-center rounded-[9px] transition-colors',
                      isEnabled ? colors.iconBg : 'bg-slate-100'
                    )}
                  >
                    <Icon className={cn('h-3 w-3', isEnabled ? colors.text : 'text-muted-foreground')} />
                  </div>
                  <div className="min-w-0">
                    <h3
                      className={cn(
                        'text-[12px] font-medium leading-[15px] transition-colors',
                        isEnabled ? 'text-slate-950' : 'text-slate-700'
                      )}
                    >
                      {feature.name}
                    </h3>
                    <p className={cn(systemPageTokens.subtle, 'mt-0.5 max-w-[62ch] truncate text-[10.5px] leading-[14px]')}>
                      {feature.description}
                    </p>
                    {feature.dependencies.length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {feature.dependencies.map((dependency) => (
                          <span
                            key={dependency}
                            className="rounded-md border border-slate-200 bg-white/75 px-1.5 py-0.5 text-[10px] leading-[14px] text-slate-500"
                          >
                            需要: {dependency}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
                <div
                  className={cn(
                    'mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full p-0.5 transition-colors',
                    isEnabled ? 'bg-blue-600' : 'bg-slate-300'
                  )}
                  aria-hidden="true"
                >
                  <span
                    className={cn(
                      'size-4 rounded-full bg-white shadow-sm transition-transform',
                      isEnabled && 'translate-x-4'
                    )}
                  />
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
