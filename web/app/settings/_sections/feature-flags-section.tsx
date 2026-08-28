'use client'

import { SettingsSwitchIndicator } from '@/components/settings/settings-switch'
import { systemPageTokens } from '@/components/ui/system-page-tokens'
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

type FeatureFlagDescriptor = {
  key: keyof FeatureFlags
  name: string
  description: string
  icon: LucideIcon
  dependencies: string[]
}

const FEATURE_FLAGS_CONFIG: FeatureFlagDescriptor[] = [
  {
    key: 'kg_enabled',
    name: 'KG 知识抽取',
    description: '启用知识图谱抽取，自动抽取文档中的实体和事件',
    icon: Sparkles,
    dependencies: ['向量数据库（Milvus）', '大语言模型（LLM）'],
  },
  {
    key: 'deepdoc_enabled',
    name: 'DeepDoc 结构化解析',
    description:
      '启用视觉 + OCR 解析能力，适合扫描件/图文混排 PDF（自动选择时生效）',
    icon: ScanLine,
    dependencies: [],
  },
  {
    key: 'docling_enabled',
    name: 'Docling 结构化解析',
    description:
      '启用 Docling 解析，对版面/表格结构抽取更友好（自动选择时生效）',
    icon: FileSearch,
    dependencies: [],
  },
  {
    key: 'etl4llm_enabled',
    name: 'ETL4LLM 版面解析',
    description:
      '启用 ETL4LLM 版面/表格/图片解析（需自建服务，自动选择时生效）',
    icon: LayoutGrid,
    dependencies: ['ETL4LLM 服务地址（API URL）'],
  },
  {
    key: 'marker_enabled',
    name: 'Marker 启发式解析',
    description:
      '启用 Marker 启发式 PDF→Markdown 解析服务（可在解析器下拉中选择）',
    icon: LayoutGrid,
    dependencies: ['Marker 服务地址（API URL）'],
  },
  {
    key: 'paddle_vl_enabled',
    name: 'PaddleOCR-VL 外部解析',
    description:
      '启用 PaddleOCR-VL 外部 OCR/版面解析服务（适合扫描件 PDF，可在解析器下拉中选择）',
    icon: ScanLine,
    dependencies: ['PaddleOCR-VL 服务地址（API URL）'],
  },
  {
    key: 'textin_enabled',
    name: 'TextIn xParse 外部解析',
    description:
      '启用 TextIn 文档解析 API（可用于 PDF/Office/图片等文档转 Markdown）',
    icon: CloudCog,
    dependencies: ['TextIn API 地址', 'TextIn APP ID', 'TextIn Secret Code'],
  },
  {
    key: 'markitdown_enabled',
    name: 'MarkItDown 文档解析',
    description:
      '启用多格式转 Markdown（Office/表格/PDF），自动选择与解析工作台会使用',
    icon: FileCode,
    dependencies: [],
  },
  {
    key: 'llama_index_enabled',
    name: 'LlamaIndex 分块',
    description: '启用 LlamaIndex 高级分块策略',
    icon: Network,
    dependencies: [],
  },
  {
    key: 'mineru_enabled',
    name: 'MinerU 解析',
    description: '启用 MinerU 本地服务或在线 API 进行复杂 PDF 解析',
    icon: CloudCog,
    dependencies: ['本地 MinerU 服务地址或 API 令牌'],
  },
  {
    key: 'magicpdf_enabled',
    name: 'MagicPDF 本地解析',
    description: '启用 magic-pdf 本地高级解析后端（可在解析器下拉中选择）',
    icon: Wand2,
    dependencies: ['magic-pdf'],
  },
]

const FEATURE_FLAG_ACTIVE_STYLE = {
  bg: 'bg-info/10',
  border: 'border-info/25',
  text: 'text-info',
  iconBg: 'bg-info/12',
} as const

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
    <section className="rounded-xl border border-info/15 bg-info/[0.025] p-3.5 shadow-none">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-[13px] font-semibold text-foreground">
            <Zap className="h-3.5 w-3.5 text-info" />
            功能开关
          </h2>
          <p className="mt-0.5 text-[11.5px] font-medium leading-[18px] text-muted-foreground">
            按需启用各项能力模块，保存后会影响后续请求；外部解析器仍需对应服务已启动
          </p>
        </div>
        <div className="inline-flex items-center gap-1.5 rounded-full border border-info/20 bg-info/10 px-2.5 py-1 text-[11px] font-medium text-info">
          <AlertCircle className="h-3 w-3" />
          <span>保存后影响后续请求</span>
        </div>
      </div>

      <div className="mt-3.5 grid grid-cols-1 gap-2 xl:grid-cols-2">
        {FEATURE_FLAGS_CONFIG.map((feature) => {
          const Icon = feature.icon
          const colors = FEATURE_FLAG_ACTIVE_STYLE
          const isEnabled = getFeatureValue(feature.key)
          const isEdited = Boolean(
            editedFeatureFlags && feature.key in editedFeatureFlags
          )

          return (
            <button
              type="button"
              key={feature.key}
              className={cn(
                'group relative w-full rounded-[13px] border px-3 py-2 text-left transition-[border-color,background-color,box-shadow] duration-150 focus-ring motion-reduce:transition-none',
                isEnabled
                  ? `${colors.border} ${colors.bg}`
                  : 'border-info/15 bg-info/[0.025] hover:border-info/25 hover:bg-info/[0.055]',
                isEdited && 'ring-2 ring-info/45 ring-offset-1'
              )}
              aria-pressed={isEnabled}
              onClick={() => toggleFeature(feature.key)}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2.5">
                  <div
                    className={cn(
                      'mt-0.5 flex size-[23px] shrink-0 items-center justify-center rounded-[9px] transition-colors',
                      isEnabled ? colors.iconBg : 'bg-info/[0.06]'
                    )}
                  >
                    <Icon
                      className={cn(
                        'h-3 w-3',
                        isEnabled ? colors.text : 'text-muted-foreground'
                      )}
                    />
                  </div>
                  <div className="min-w-0">
                    <h3
                      className={cn(
                        'text-[12px] font-semibold leading-[15px] transition-colors',
                        isEnabled ? 'text-foreground' : 'text-foreground/78'
                      )}
                    >
                      {feature.name}
                    </h3>
                    <p
                      className={cn(
                        systemPageTokens.subtle,
                        'mt-0.5 max-w-[62ch] truncate text-[10.5px] leading-[14px]'
                      )}
                    >
                      {feature.description}
                    </p>
                    {feature.dependencies.length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {feature.dependencies.map((dependency) => (
                          <span
                            key={dependency}
                            className="rounded-md border border-info/15 bg-info/[0.035] px-1.5 py-0.5 text-[10px] font-medium leading-[14px] text-muted-foreground"
                          >
                            需要: {dependency}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </div>
                <SettingsSwitchIndicator checked={isEnabled} className="mt-0.5" />
              </div>
            </button>
          )
        })}
      </div>
    </section>
  )
}
