'use client'

import { CheckCircle2, CircleDashed, ChevronRight } from '@/components/icons'
import { ProviderIcon } from '@/components/provider-icon'
import type { ModelProvider } from '@/types/models'

interface ModelProviderCardProps { provider: ModelProvider; onConfigure: (provider: ModelProvider) => void }

export function ModelProviderCard({ provider, onConfigure }: Readonly<ModelProviderCardProps>) {
  return (
    <button type="button" onClick={() => onConfigure(provider)} className="group flex w-full min-w-0 items-center gap-3 border-b border-border/50 py-3 text-left transition-colors hover:bg-muted/40 focus-ring motion-reduce:transition-none">
      <ProviderIcon providerId={provider.id} className="size-8 shrink-0 object-contain" />
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium leading-5 text-foreground">{provider.name}</span>
        <span className="mt-1 block text-[13px] leading-5 text-muted-foreground">{provider.description}</span>
        <span className="mt-1 block break-all text-xs leading-5 text-muted-foreground">{provider.isConfigured && provider.config?.model ? provider.config.model : `${provider.models.length} 个可选模型`}</span>
      </span>
      <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs text-muted-foreground">
        {provider.isConfigured ? <CheckCircle2 className="size-3.5 text-success" /> : <CircleDashed className="size-3.5" />}
        {provider.isConfigured ? '已配置' : '未配置'}
      </span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none" />
    </button>
  )
}
