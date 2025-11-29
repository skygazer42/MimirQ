/**
 * 模型提供商图标组件
 * 支持 SVG 和 PNG 格式的品牌 Logo
 */
import Image from 'next/image'

interface ProviderIconProps {
  providerId: string
  className?: string
}

// 提供商 ID 到图标文件的映射
const PROVIDER_ICONS: Record<string, { file: string; format: 'svg' | 'png' }> = {
  // PNG 格式（来自 providers 目录）
  openai: { file: 'openai', format: 'png' },
  deepseek: { file: 'deepseek', format: 'png' },
  zhipu: { file: 'zhipuai', format: 'png' },
  zhipuai: { file: 'zhipuai', format: 'png' },
  qwen: { file: 'dashscope', format: 'png' },
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
}

// 默认图标
const DEFAULT_ICON = { file: 'default', format: 'png' as const }

export function ProviderIcon({ providerId, className = 'w-8 h-8' }: ProviderIconProps) {
  const icon = PROVIDER_ICONS[providerId.toLowerCase()] || DEFAULT_ICON
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
