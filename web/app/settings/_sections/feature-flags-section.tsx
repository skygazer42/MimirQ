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
  ToggleLeft,
  ToggleRight,
  Wand2,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { systemPageTokens, systemWorkbenchTokens } from '@/components/ui/system-page-tokens'

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
      bg: 'bg-primary/10',
      border: 'border-primary/25',
      text: 'text-primary',
      iconBg: 'bg-primary/15',
    },
    info: {
      bg: 'bg-info/10',
      border: 'border-info/25',
      text: 'text-info',
      iconBg: 'bg-info/15',
    },
    success: {
      bg: 'bg-success/10',
      border: 'border-success/25',
      text: 'text-success',
      iconBg: 'bg-success/15',
    },
    warning: {
      bg: 'bg-warning/10',
      border: 'border-warning/25',
      text: 'text-warning',
      iconBg: 'bg-warning/15',
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
    <section className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold tracking-[-0.01em] text-foreground">
          <Zap className="h-4 w-4 text-warning" />
          功能开关
        </h2>
        <div className="inline-flex items-center gap-1.5 rounded-full border border-warning/20 bg-warning/10 px-2.5 py-1 text-[11px] font-semibold text-warning">
          <AlertCircle className="h-3.5 w-3.5" />
          <span>更改后需重启后端生效</span>
        </div>
      </div>

      <div className={cn('grid grid-cols-1 gap-2 xl:grid-cols-2', systemWorkbenchTokens.divider)}>
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
                'group relative w-full rounded-lg border px-3 py-2.5 text-left transition-colors duration-150 focus-ring motion-reduce:transition-none',
                isEnabled ? `${colors.border} ${colors.bg}` : 'border-border/70 bg-background hover:bg-muted/15',
                isEdited && 'ring-2 ring-blue-400/70 ring-offset-1'
              )}
              aria-pressed={isEnabled}
              onClick={() => toggleFeature(feature.key)}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-2.5">
                  <div
                    className={cn(
                      'mt-0.5 rounded-md p-1.5 transition-colors',
                      isEnabled ? colors.iconBg : 'bg-muted'
                    )}
                  >
                    <Icon className={cn('h-4 w-4', isEnabled ? colors.text : 'text-muted-foreground')} />
                  </div>
                  <div className="min-w-0">
                    <h3
                      className={cn(
                        'text-[13px] font-semibold leading-5 transition-colors',
                        isEnabled ? 'text-foreground' : 'text-muted-foreground'
                      )}
                    >
                      {feature.name}
                    </h3>
                    <p className={cn(systemPageTokens.subtle, 'mt-0.5 leading-4')}>
                      {feature.description}
                    </p>
                    {feature.dependencies.length > 0 ? (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {feature.dependencies.map((dependency) => (
                          <span
                            key={dependency}
                            className="rounded border border-border/70 bg-muted/30 px-1.5 py-0.5 text-[11px] leading-4 text-muted-foreground"
                          >
                            需要: {dependency}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
                <div className="flex-shrink-0 pt-0.5">
                  {isEnabled ? (
                    <ToggleRight className={cn('h-6 w-6', colors.text)} />
                  ) : (
                    <ToggleLeft className="h-6 w-6 text-muted-foreground group-hover:text-muted-foreground" />
                  )}
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
