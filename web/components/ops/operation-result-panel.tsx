'use client'

import { cn } from '@/lib/utils'

type OperationResult = {
  title: string
  payload: unknown
}

type OperationResultPanelProps = {
  title: string
  result: OperationResult | null
  emptyMessage: string
  className?: string
}

function formatResponse(value: unknown): string {
  try {
    const json = JSON.stringify(value, null, 2)
    return json === undefined ? '响应无正文。' : json
  } catch {
    return '响应内容无法转换为 JSON。'
  }
}

export function OperationResultPanel({ title, result, emptyMessage, className }: Readonly<OperationResultPanelProps>) {
  return (
    <div className={cn('rounded-lg border border-border/60 bg-muted/20 p-3', className)}>
      <div className="text-xs font-semibold text-foreground">{result === null ? title : result.title}</div>
      {result !== null ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs font-semibold text-primary">查看原始响应</summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-md border border-border/60 bg-background p-2 text-xs whitespace-pre-wrap break-words">
            {formatResponse(result.payload)}
          </pre>
        </details>
      ) : (
        <div className="mt-2 rounded-md border border-dashed border-border/70 bg-background/65 px-3 py-2 text-xs leading-5 text-muted-foreground">
          {emptyMessage}
        </div>
      )}
    </div>
  )
}
