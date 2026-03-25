'use client'

import type { BackendMeta, SystemStatus } from '@/lib/api'
import { cn } from '@/lib/utils'
import { CheckCircle2, Database, XCircle } from 'lucide-react'

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
        'rounded-xl border bg-card p-4 transition-colors',
        connected
          ? 'border-green-200 dark:border-green-500/40'
          : 'border-red-200 dark:border-red-500/40'
      )}
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium text-foreground/80">{label}</span>
        {connected ? (
          <CheckCircle2 className="h-5 w-5 text-green-500 dark:text-green-300" />
        ) : (
          <XCircle className="h-5 w-5 text-red-500 dark:text-red-300" />
        )}
      </div>
      <p
        className={cn(
          'truncate text-xs',
          connected ? 'text-green-600 dark:text-green-300' : 'text-red-600 dark:text-red-300'
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
    <section>
      <h2 className="mb-6 flex items-center gap-2 text-lg font-semibold text-foreground">
        <Database className="h-5 w-5 text-primary" />
        系统状态
      </h2>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
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
          label="LLM"
          connected={status.llm.configured}
          message={status.llm.model}
        />
        <StatusCard
          label="Embedding"
          connected={status.embedding.configured}
          message={status.embedding.model}
        />
      </div>

      {backendMeta ? (
        <div className="mt-6 rounded-2xl border border-border bg-card p-5 shadow-sm">
          <div className="mb-3 text-sm font-medium text-foreground/80">Backend</div>
          <div className="space-y-2 text-xs text-muted-foreground">
            <div>
              API: {backendMeta.name} ({backendMeta.api_version})
              {backendMeta.build?.sha ? ` @ ${backendMeta.build.sha.slice(0, 7)}` : ''}
            </div>
            {backendMeta.features ? (
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full border border-border bg-muted px-2 py-0.5">
                  auth={backendMeta.features.auth_mode || '-'}
                </span>
                <span className="rounded-full border border-border bg-muted px-2 py-0.5">
                  vector={backendMeta.features.vector_backend || '-'}
                </span>
                {typeof backendMeta.features.task_queue_enabled === 'boolean' ? (
                  <span className="rounded-full border border-border bg-muted px-2 py-0.5">
                    queue={backendMeta.features.task_queue_enabled ? 'on' : 'off'}
                  </span>
                ) : null}
              </div>
            ) : null}
            {backendMeta.runtime?.python ? <div>Runtime: Python {backendMeta.runtime.python}</div> : null}
          </div>
        </div>
      ) : null}

      {status.parsers ? (
        <div className="mt-6 rounded-2xl border border-border bg-card p-5 shadow-sm">
          <div className="mb-3 text-sm font-medium text-foreground/80">解析器状态</div>
          <div className="flex flex-wrap gap-2">
            {Object.entries(status.parsers).map(([key, info]) => (
              <span
                key={key}
                title={info.message}
                className={cn(
                  'rounded-full border px-2.5 py-1 text-xs',
                  info.available
                    ? 'border-green-200 bg-green-50 text-green-700 dark:border-green-500/30 dark:bg-green-500/10 dark:text-green-300'
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
