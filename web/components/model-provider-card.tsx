/**
 * 模型提供商卡片组件
 */
'use client'

import { Settings, CheckCircle2, CircleDashed, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { ProviderIcon } from '@/components/provider-icon'
import { Badge } from '@/components/ui/badge'
import type { ModelProvider } from '@/types/models'

interface ModelProviderCardProps {
  provider: ModelProvider
  onConfigure: (provider: ModelProvider) => void
}

export function ModelProviderCard({ provider, onConfigure }: Readonly<ModelProviderCardProps>) {
  return (
    <button
      type="button"
      className={cn(
        'group relative flex h-full w-full flex-col rounded-2xl border bg-card p-5 text-left shadow-soft transition-colors transition-shadow duration-200 motion-reduce:transition-none focus-ring',
        provider.isConfigured
          ? 'border-primary/25 ring-1 ring-primary/10 hover:border-primary/35 hover:shadow-strong'
          : 'border-border hover:border-primary/25 hover:shadow-strong'
      )}
      onClick={() => onConfigure(provider)}
    >
      {/* 头部：Logo 和状态 */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <div className="h-11 w-11 shrink-0 rounded-xl border border-border bg-muted/30 flex items-center justify-center transition-all duration-200 motion-reduce:transition-none group-hover:motion-safe:scale-105 group-hover:bg-muted/60">
            <ProviderIcon providerId={provider.id} className="size-8 object-contain" />
          </div>

          <div className="min-w-0">
            <h3 className="text-base font-semibold text-foreground truncate">
              {provider.name}
            </h3>
            <p className="mt-1 text-xs text-muted-foreground leading-relaxed line-clamp-2">
              {provider.description}
            </p>
          </div>
        </div>
        
        <Badge
          variant={provider.isConfigured ? 'success' : 'soft'}
          className="gap-1.5 text-[11px] px-2.5 py-1 font-medium"
        >
          {provider.isConfigured ? (
            <>
              <CheckCircle2 className="size-3.5" />
              <span>已连接</span>
            </>
          ) : (
            <>
              <CircleDashed className="size-3.5" />
              <span>未配置</span>
            </>
          )}
        </Badge>
      </div>

      {/* 模型标签 */}
      <div className="mt-4 flex flex-wrap gap-1.5">
        {provider.models.slice(0, 3).map((model) => (
          <span
            key={model.id}
            className="inline-flex items-center rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
          >
            {model.displayName}
          </span>
        ))}
        {provider.models.length > 3 && (
          <span className="inline-flex items-center rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground/70">
            +{provider.models.length - 3}
          </span>
        )}
      </div>

      {/* 底部操作 */}
      <div className="mt-auto pt-4 border-t border-border/40 flex items-center justify-between text-xs">
        <span
          className={cn(
            'font-medium flex items-center gap-1.5 transition-colors motion-reduce:transition-none',
            provider.isConfigured ? 'text-primary' : 'text-muted-foreground group-hover:text-primary'
          )}
        >
          <Settings className="size-3.5" />
          {provider.isConfigured ? '管理配置' : '去配置'}
        </span>
        
        {/* 仅在 Hover 时显示的箭头或图标 */}
        <ChevronRight className="size-4 text-muted-foreground/60 opacity-0 translate-x-[-4px] group-hover:opacity-100 group-hover:translate-x-0 transition-opacity transition-transform duration-200 motion-reduce:transition-none" />
      </div>
    </button>
  )
}
