'use client'

import type { BackendMetaDetails, SystemStatus } from '@/lib/api'
import { cn } from '@/lib/utils'
import { CheckCircle2, Server, XCircle } from 'lucide-react'
import { systemPageTokens } from '@/components/ui/system-page-tokens'

type SystemStatusSectionProps = {
  status: SystemStatus
  backendMeta: BackendMetaDetails | null
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

function formatParserName(key: string): string {
  const labels: Record<string, string> = {
    basic: '基础解析',
    markitdown: 'MarkItDown',
    pandoc: 'Pandoc',
    libreoffice: 'LibreOffice',
    deepdoc: 'DeepDoc',
    deepseek_ocr: 'DeepSeek OCR',
    qianfan_ocr: '千帆 OCR',
    etl4llm: 'ETL4LLM',
    marker: 'Marker',
    paddle_vl: 'PaddleOCR-VL',
    textin: 'TextIn',
    olmocr: 'OLMOCR',
    docling: 'Docling',
    mineru: 'MinerU',
    magicpdf: 'MagicPDF',
  }
  return labels[key] || key
}

export function SystemStatusSection({
  status,
  backendMeta,
}: Readonly<SystemStatusSectionProps>) {
  const parserEntries = Object.entries(status.parsers || {})

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

      {backendMeta || parserEntries.length ? (
        <div className="rounded-lg border border-border/70 bg-card p-3.5 shadow-none">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className={cn(systemPageTokens.microLabel, 'flex items-center gap-1.5 text-foreground/80')}>
                <Server className="h-3.5 w-3.5 text-primary" />
                运行能力
              </div>
              <div className="mt-1 text-[11px] font-medium leading-5 text-muted-foreground">
                API、运行环境与解析器可用性汇总
              </div>
            </div>
            {backendMeta ? (
              <div className="text-right text-[11px] font-medium leading-5 text-muted-foreground">
                <div className="text-foreground">
                  {backendMeta.name} · {backendMeta.api_version}
                  {backendMeta.build?.sha ? ` · ${backendMeta.build.sha.slice(0, 7)}` : ''}
                </div>
                {backendMeta.runtime?.python ? <div>Python {backendMeta.runtime.python}</div> : null}
              </div>
            ) : null}
          </div>

          <div className="flex flex-wrap gap-1.5 border-t border-border/50 pt-3">
            {parserEntries.map(([key, info]) => (
              <span
                key={key}
                title={info.message || formatParserName(key)}
                className={cn(
                  'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[11px] font-semibold',
                  info.available
                    ? 'border-success/25 bg-success/10 text-success'
                    : 'border-border/60 bg-muted/35 text-muted-foreground'
                )}
              >
                <span
                  className={cn(
                    'size-1.5 rounded-full',
                    info.available ? 'bg-success' : 'bg-muted-foreground/45'
                  )}
                />
                {formatParserName(key)}
                <span className="font-medium opacity-75">
                  {info.available ? '可用' : '未启用'}
                </span>
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  )
}
