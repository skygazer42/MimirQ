/**
 * 模型提供商图标组件
 * 支持 SVG 和 PNG 格式的品牌 Logo
 */
import Image from 'next/image'

interface ProviderIconProps {
  providerId: string
  className?: string
}

/**
 * 优先使用 LobeHub 彩色 SVG（web/public/logos/lobehub/*.svg）。
 * 无匹配时回退到旧的 /public/logos 资源映射，避免历史 providerId 断裂。
 */
const LOBEHUB_ICON_BY_PROVIDER_ID: Record<string, string> = {
  openai: 'openai',
  'openai-embedding': 'openai',

  anthropic: 'anthropic',

  deepseek: 'deepseek',

  zhipu: 'zhipu',
  zhipuai: 'zhipu',

  qwen: 'qwen',
  'qwen-embedding': 'qwen',
  dashscope: 'qwen',

  moonshot: 'moonshot',
  ollama: 'ollama',

  // 产品/提供商别名
  ark: 'doubao',
  doubao: 'doubao',

  lingyiwanwu: 'yi',
  yi: 'yi',

  qianfan: 'wenxin',
  baidu: 'wenxin',
  wenxin: 'wenxin',

  siliconflow: 'siliconcloud',
  siliconcloud: 'siliconcloud',

  openrouter: 'openrouter',
  openrouterai: 'openrouter',

  together: 'together',
  togetherai: 'together',

  'cohere-reranker': 'cohere',
  cohere: 'cohere',

  'jina-reranker': 'jina',
  jina: 'jina',
}

function normalizeProviderId(providerId: string): string {
  return String(providerId || '').trim().toLowerCase()
}

// 提供商 ID 到图标文件的映射（旧资源兜底）
const PROVIDER_ICONS: Record<string, { file: string; format: 'svg' | 'png' }> = {
  // PNG 格式（来自 providers 目录）
  openai: { file: 'openai', format: 'png' },
  deepseek: { file: 'deepseek', format: 'png' },
  zhipu: { file: 'zhipuai', format: 'png' },
  zhipuai: { file: 'zhipuai', format: 'png' },
  qwen: { file: 'dashscope', format: 'png' },
  'qwen-embedding': { file: 'dashscope', format: 'png' },
  dashscope: { file: 'dashscope', format: 'png' },
  ark: { file: 'ark', format: 'png' },
  lingyiwanwu: { file: 'lingyiwanwu', format: 'png' },
  yi: { file: 'lingyiwanwu', format: 'png' },
  openrouter: { file: 'openrouterai', format: 'png' },
  openrouterai: { file: 'openrouterai', format: 'png' },
  qianfan: { file: 'qianfan', format: 'png' },
  baidu: { file: 'qianfan', format: 'png' },
  siliconflow: { file: 'siliconflow', format: 'png' },
  together: { file: 'together.ai', format: 'png' },
  togetherai: { file: 'together.ai', format: 'png' },
  // SVG 格式（保留原有的）
  anthropic: { file: 'anthropic', format: 'svg' },
  moonshot: { file: 'moonshot', format: 'svg' },
  ollama: { file: 'ollama', format: 'svg' },
  local: { file: 'local', format: 'svg' },
  'local-embedding': { file: 'local', format: 'svg' },
  reranker: { file: 'reranker', format: 'svg' },
  'local-reranker': { file: 'reranker', format: 'svg' },
}

// 默认图标
const DEFAULT_ICON = { file: 'default', format: 'png' }

export function ProviderIcon({ providerId, className = 'w-8 h-8' }: Readonly<ProviderIconProps>) {
  const pid = normalizeProviderId(providerId)
  const lobehubIconName = LOBEHUB_ICON_BY_PROVIDER_ID[pid]

  if (lobehubIconName) {
    return (
      <Image
        src={`/logos/lobehub/${lobehubIconName}.svg`}
        alt={`${providerId} logo`}
        width={32}
        height={32}
        className={className}
        priority
        unoptimized
      />
    )
  }

  const icon = PROVIDER_ICONS[pid] || DEFAULT_ICON
  const src = `/logos/${icon.file}.${icon.format}`

  return (
    <Image
      src={src}
      alt={`${providerId} logo`}
      width={32}
      height={32}
      className={className}
      priority
      unoptimized={icon.format === 'png'}
    />
  )
}
