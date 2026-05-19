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
        'group relative flex h-full w-full flex-col rounded-lg border bg-card p-3.5 text-left shadow-none transition-colors duration-150 motion-reduce:transition-none focus-ring',
        provider.isConfigured
          ? 'border-primary/25 ring-1 ring-primary/10 hover:border-primary/35 hover:shadow-strong'
          : 'border-border/70 hover:border-primary/25'
      )}
      onClick={() => onConfigure(provider)}
    >
      {/* 头部：Logo 和状态 */}
      <div className="flex items-start justify-between gap-2.5">
        <div className="flex min-w-0 items-start gap-2.5">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border/70 bg-muted/30 transition-colors duration-150 motion-reduce:transition-none group-hover:bg-muted/55">
            <ProviderIcon providerId={provider.id} className="size-7 object-contain" />
          </div>

          <div className="min-w-0">
            <h3 className="truncate text-[13px] font-semibold leading-5 text-slate-950">
              {provider.name}
            </h3>
            <p className="mt-0.5 line-clamp-2 text-[11px] font-medium leading-4 text-slate-600">
              {provider.description}
            </p>
          </div>
        </div>

        <Badge
          variant={provider.isConfigured ? 'success' : 'soft'}
          className="gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold leading-4"
        >
          {provider.isConfigured ? (
            <>
              <CheckCircle2 className="size-3" />
              <span>已连接</span>
            </>
          ) : (
            <>
              <CircleDashed className="size-3" />
              <span>未配置</span>
            </>
          )}
        </Badge>
      </div>

      {/* 模型标签 */}
      <div className="mt-2.5 flex flex-wrap gap-1">
        {provider.models.slice(0, 3).map((model) => (
          <span
            key={model.id}
            className="inline-flex items-center rounded-md border border-slate-200/80 bg-slate-50/80 px-1.5 py-0.5 text-[11px] font-medium leading-4 text-slate-700"
          >
            {model.displayName}
          </span>
        ))}
        {provider.models.length > 3 && (
          <span className="inline-flex items-center rounded-md border border-slate-200/80 bg-slate-50/80 px-1.5 py-0.5 text-[11px] font-medium leading-4 text-slate-600">
            +{provider.models.length - 3}
          </span>
        )}
      </div>

      {/* 底部操作 */}
      <div className="mt-auto flex items-center justify-between border-t border-border/40 pt-2.5 text-[11px]">
        <span
          className={cn(
            'flex items-center gap-1 font-semibold transition-colors motion-reduce:transition-none',
            provider.isConfigured ? 'text-primary' : 'text-slate-600 group-hover:text-primary'
          )}
        >
          <Settings className="size-3.5" />
          {provider.isConfigured ? '管理配置' : '去配置'}
        </span>

        {/* 仅在 Hover 时显示的箭头或图标 */}
        <ChevronRight className="size-3.5 -translate-x-1 text-muted-foreground/60 opacity-0 transition-all duration-150 motion-reduce:transition-none group-hover:translate-x-0 group-hover:opacity-100" />
      </div>
    </button>
  )
}
