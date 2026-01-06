'use client'

import { Info } from 'lucide-react'
import { cn } from '@/lib/utils'
import { PARSER_BACKEND_OPTIONS, getParserOption } from '@/lib/parser-options'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'

interface ParserBackendSelectProps {
  label?: string
  className?: string
  compact?: boolean
}

export function ParserBackendSelect({
  label = '解析方式',
  className,
  compact = false,
}: ParserBackendSelectProps) {
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { parserBackendAvailable } = usePipelineCapabilities()
  const currentOption = getParserOption(parserBackend)

  return (
    <div
      className={cn(
        'flex flex-col gap-1 rounded-lg border border-gray-200 bg-white p-3',
        !compact && 'shadow-sm',
        className
      )}
    >
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span className="font-medium text-gray-700">{label}</span>
        <div className="flex items-center gap-1 text-[11px] text-gray-400">
          <Info className="h-3 w-3" />
          <span>影响解析、切块和上传流程</span>
        </div>
      </div>

      <select
        value={parserBackend}
        onChange={(e) => setParserBackend(e.target.value)}
        className={cn(
          'mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200',
          compact && 'py-1.5 text-xs'
        )}
      >
        {PARSER_BACKEND_OPTIONS.map((option) => (
          <option key={option.value} value={option.value} disabled={parserBackendAvailable(option.value) === false}>
            {option.label}
          </option>
        ))}
      </select>

      {!compact && (
        <p className="text-xs text-gray-500 leading-tight">
          {currentOption.description}
        </p>
      )}
    </div>
  )
}
