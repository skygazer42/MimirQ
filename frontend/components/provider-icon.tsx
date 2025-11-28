/**
 * 模型提供商图标组件
 * 使用真实的品牌 Logo 图片
 */
import Image from 'next/image'

interface ProviderIconProps {
  providerId: string
  className?: string
}

export function ProviderIcon({ providerId, className = 'w-8 h-8' }: ProviderIconProps) {
  return (
    <Image
      src={`/logos/${providerId}.svg`}
      alt={`${providerId} logo`}
      width={32}
      height={32}
      className={className}
      priority
    />
  )
}
