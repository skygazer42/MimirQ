import Image from 'next/image'
import { LocalModel, Model, Reranker } from '@/components/icons'
import { cn } from '@/lib/utils'

type ProviderIconProps = {
  providerId: string
  className?: string
}

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

// These source marks use black paths and need a light silhouette on dark surfaces.
const DARK_MONOCHROME_MARKS = new Set([
  'openai',
  'anthropic',
  'moonshot',
  'ollama',
  'openrouter',
  'yi',
  'jina',
  'together',
])

export function ProviderIcon({ providerId, className = 'w-8 h-8' }: Readonly<ProviderIconProps>) {
  const normalizedProviderId = providerId.trim().toLowerCase()

  if (Object.hasOwn(LOBEHUB_ICON_BY_PROVIDER_ID, normalizedProviderId)) {
    const lobehubIconName = LOBEHUB_ICON_BY_PROVIDER_ID[normalizedProviderId]
    return (
      <Image
        src={`/logos/lobehub/${lobehubIconName}.svg`}
        alt={`${providerId} logo`}
        width={32}
        height={32}
        className={cn(className, DARK_MONOCHROME_MARKS.has(lobehubIconName) && 'dark:brightness-0 dark:invert')}
        priority
        unoptimized
      />
    )
  }

  if (normalizedProviderId === 'local' || normalizedProviderId === 'local-embedding') {
    return <LocalModel className={className} aria-label="本地模型" />
  }
  if (normalizedProviderId === 'reranker' || normalizedProviderId === 'local-reranker') {
    return <Reranker className={className} aria-label="重排序模型" />
  }

  const label = normalizedProviderId === '' ? '自定义模型' : `${providerId}模型`
  return <Model className={className} aria-label={label} />
}
