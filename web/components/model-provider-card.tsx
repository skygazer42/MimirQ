'use client'

import { CheckCircle2, CircleDashed, ChevronRight } from '@/components/icons'
import { ProviderIcon } from '@/components/provider-icon'
import type { ModelProvider } from '@/types/models'

type ModelProviderCardProps = {
  provider: ModelProvider
  onConfigure: (provider: ModelProvider) => void
}

export function ModelProviderCard({ provider, onConfigure }: Readonly<ModelProviderCardProps>) {
  const modelName = provider.config?.model
  const modelSummary =
    provider.isConfigured && modelName !== undefined && modelName !== ''
      ? modelName
      : `${provider.models.length} 个可选模型`

  return (
    <button
      type="button"
      onClick={() => onConfigure(provider)}
      title={provider.description}
      className="group flex w-full min-w-0 items-center gap-3 border-b border-border/50 py-3 text-left transition-colors hover:bg-muted/40 focus-ring motion-reduce:transition-none"
    >
      <ProviderIcon providerId={provider.id} className="size-6 shrink-0 object-contain" />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium leading-5 text-foreground">{provider.name}</span>
        <span className="mt-1 block break-words text-xs leading-5 text-muted-foreground">{modelSummary}</span>
      </span>
      <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs text-muted-foreground">
        {provider.isConfigured ? (
          <CheckCircle2 className="size-3.5 text-success" />
        ) : (
          <CircleDashed className="size-3.5" />
        )}
        {provider.isConfigured ? '已配置' : '未配置'}
      </span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none" />
    </button>
  )
}
