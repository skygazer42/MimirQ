'use client'

import { SettingsSwitchIndicator } from '@/components/settings/settings-switch'
import type { FeatureFlags } from '@/lib/api'
import {
  CloudCog,
  FileCode,
  FileSearch,
  LayoutGrid,
  Network,
  ScanLine,
  Sparkles,
  Wand2,
} from '@/components/icons'
import type { PlatformIcon } from '@/components/icons'

type FeatureFlagDescriptor = {
  key: keyof FeatureFlags
  name: string
  description: string
  icon: PlatformIcon
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

type FeatureFlagsSectionProps = {
  getFeatureValue: (key: keyof FeatureFlags) => boolean
  toggleFeature: (key: keyof FeatureFlags) => void
}

export function FeatureFlagsSection({
  getFeatureValue,
  toggleFeature,
}: Readonly<FeatureFlagsSectionProps>) {
  return (
    <div className="grid grid-cols-1 gap-x-8 xl:grid-cols-2">
      {FEATURE_FLAGS_CONFIG.map((feature) => {
        const Icon = feature.icon
        const enabled = getFeatureValue(feature.key)
        return (
          <button type="button" key={feature.key} aria-pressed={enabled} onClick={() => toggleFeature(feature.key)} className="flex min-h-16 w-full items-center justify-between gap-4 border-b border-border/50 py-3 text-left transition-colors hover:bg-muted/40 focus-ring motion-reduce:transition-none">
            <span className="flex min-w-0 items-start gap-3">
              <Icon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0">
                <span className="block text-sm font-medium leading-5 text-foreground">{feature.name}</span>
                <span className="mt-1 block text-[13px] leading-5 text-muted-foreground">{feature.description}</span>
                {feature.dependencies.length > 0 ? <span className="mt-1 block text-xs leading-5 text-muted-foreground">需要：{feature.dependencies.join('、')}</span> : null}
              </span>
            </span>
            <SettingsSwitchIndicator checked={enabled} />
          </button>
        )
      })}
    </div>
  )
}
