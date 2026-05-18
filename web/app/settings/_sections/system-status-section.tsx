'use client'

import type { BackendMeta, SystemStatus } from '@/lib/api'
import { cn } from '@/lib/utils'
import { CheckCircle2, XCircle } from 'lucide-react'
import { systemPageTokens } from '@/components/ui/system-page-tokens'

type SystemStatusSectionProps = {
  status: SystemStatus
  backendMeta: BackendMeta | null
}

function StatusCard({
  label,
  connected,
  message,
}: Readonly<{ label: string; connected: boolean; message: string }>) {
  return (
    <div
      className={cn(
        'rounded-lg border bg-card px-3 py-2.5 transition-colors',
        connected
          ? 'border-success/20'
          : 'border-destructive/20'
      )}
    >
      <div className="mb-1.5 flex items-center justify-between">
        <span className={cn(systemPageTokens.microLabel, 'text-foreground/80')}>{label}</span>
        {connected ? (
          <CheckCircle2 className="h-4 w-4 text-success" />
        ) : (
          <XCircle className="h-4 w-4 text-destructive" />
        )}
      </div>
      <p
        className={cn(
          'truncate text-[11px]',
          connected ? 'text-success' : 'text-destructive'
        )}
      >
        {message || (connected ? '已连接' : '未连接')}
      </p>
    </div>
  )
}

export function SystemStatusSection({
  status,
  backendMeta,
}: Readonly<SystemStatusSectionProps>) {
  return (
    <section className="space-y-3">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <StatusCard
          label="PostgreSQL"
          connected={status.database.connected}
          message={status.database.message}
        />
        <StatusCard
          label="Milvus"
          connected={status.milvus.connected}
          message={status.milvus.message}
        />
        <StatusCard
          label="大语言模型（LLM）"
          connected={status.llm.configured}
          message={status.llm.model}
        />
        <StatusCard
          label="向量模型（Embedding）"
          connected={status.embedding.configured}
          message={status.embedding.model}
        />
      </div>

      {backendMeta ? (
        <div className="rounded-lg border border-border/70 bg-card p-4 shadow-none">
          <div className={cn('mb-2', systemPageTokens.microLabel, 'text-foreground/80')}>后端信息</div>
          <div className="space-y-1.5 text-[11px] text-muted-foreground">
            <div>
              API: {backendMeta.name} ({backendMeta.api_version})
              {backendMeta.build?.sha ? ` @ ${backendMeta.build.sha.slice(0, 7)}` : ''}
            </div>
            {backendMeta.features ? (
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full border border-border bg-muted px-2 py-0.5 font-mono">
                  鉴权模式（auth_mode）={backendMeta.features.auth_mode || '-'}
                </span>
                <span className="rounded-full border border-border bg-muted px-2 py-0.5 font-mono">
                  向量后端（vector_backend）={backendMeta.features.vector_backend || '-'}
                </span>
                {typeof backendMeta.features.task_queue_enabled === 'boolean' ? (
                  <span className="rounded-full border border-border bg-muted px-2 py-0.5 font-mono">
                    任务队列（task_queue_enabled）={backendMeta.features.task_queue_enabled ? '开' : '关'}
                  </span>
                ) : null}
              </div>
            ) : null}
            {backendMeta.runtime?.python ? <div>运行时: Python {backendMeta.runtime.python}</div> : null}
          </div>
        </div>
      ) : null}

      {status.parsers ? (
        <div className="rounded-lg border border-border/70 bg-card p-4 shadow-none">
          <div className={cn('mb-2', systemPageTokens.microLabel, 'text-foreground/80')}>解析器状态</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(status.parsers).map(([key, info]) => (
              <span
                key={key}
                title={info.message}
                className={cn(
                  'rounded-full border px-2 py-0.5 text-[11px] font-mono',
                  info.available
                    ? 'border-success/20 bg-success/10 text-success'
                    : 'border-border bg-muted text-muted-foreground'
                )}
              >
                {key} {info.available ? '可用' : '不可用'}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  )
}
