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
    dependencies: ['Milvus', 'LLM'],
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
    dependencies: ['ETL4LLM API URL'],
  },
  {
    key: 'marker_enabled',
    name: 'Marker 启发式解析',
    description: '启用 Marker 启发式 PDF→Markdown 解析服务（可在解析器下拉中选择）',
    icon: LayoutGrid,
    color: 'green',
    dependencies: ['Marker API URL'],
  },
  {
    key: 'paddle_vl_enabled',
    name: 'PaddleOCR-VL 外部解析',
    description: '启用 PaddleOCR-VL 外部 OCR/版面解析服务（适合扫描件 PDF，可在解析器下拉中选择）',
    icon: ScanLine,
    color: 'orange',
    dependencies: ['PaddleOCR-VL API URL'],
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
    name: 'MinerU API',
    description: '使用 MinerU 在线 API 进行文档解析',
    icon: CloudCog,
    color: 'cyan',
    dependencies: ['MinerU API Token'],
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
    <section>
      <div className="mb-6 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-foreground">
          <Zap className="h-5 w-5 text-warning" />
          功能开关
        </h2>
        <div className="flex items-center gap-2 rounded-full border border-warning/20 bg-warning/10 px-3 py-1 text-xs font-medium text-warning">
          <AlertCircle className="h-3 w-3" />
          <span>更改后需重启后端生效</span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
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
                'group relative w-full rounded-xl border-2 bg-card p-5 text-left transition-colors duration-200 focus-ring motion-reduce:transition-none',
                isEnabled ? `${colors.border} ${colors.bg}` : 'border-border hover:border-border',
                isEdited && 'ring-2 ring-blue-400 ring-offset-2'
              )}
              aria-pressed={isEnabled}
              onClick={() => toggleFeature(feature.key)}
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3">
                  <div
                    className={cn(
                      'rounded-lg p-2 transition-colors',
                      isEnabled ? colors.iconBg : 'bg-muted'
                    )}
                  >
                    <Icon className={cn('h-5 w-5', isEnabled ? colors.text : 'text-muted-foreground')} />
                  </div>
                  <div>
                    <h3
                      className={cn(
                        'font-medium transition-colors',
                        isEnabled ? 'text-foreground' : 'text-muted-foreground'
                      )}
                    >
                      {feature.name}
                    </h3>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                      {feature.description}
                    </p>
                    {feature.dependencies.length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {feature.dependencies.map((dependency) => (
                          <span
                            key={dependency}
                            className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                          >
                            需要: {dependency}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
                <div className="flex-shrink-0">
                  {isEnabled ? (
                    <ToggleRight className={cn('h-8 w-8', colors.text)} />
                  ) : (
                    <ToggleLeft className="h-8 w-8 text-muted-foreground group-hover:text-muted-foreground" />
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
