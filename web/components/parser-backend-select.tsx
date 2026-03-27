'use client'

import { Info } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getParserOption } from '@/lib/parser-options'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { Panel } from '@/components/ui/panel'

interface ParserBackendSelectProps {
  label?: string
  className?: string
  compact?: boolean
}

export function ParserBackendSelect({
  label = '解析方式',
  className,
  compact = false,
}: Readonly<ParserBackendSelectProps>) {
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const currentOption = getParserOption(parserBackend)

  return (
    <Panel
      padding={compact ? "sm" : "md"}
      className={cn("space-y-2", className)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-0.5">
          <div className="text-xs font-semibold text-foreground">{label}</div>
          {compact ? null : (
            <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
              <Info className="h-3.5 w-3.5" />
              <span>影响解析、切块和上传流程</span>
            </div>
          )}
        </div>
      </div>

      <ParserDropdown value={parserBackend} onChange={setParserBackend} compact={compact} />

      {compact ? null : (
        <p className="text-xs leading-relaxed text-muted-foreground">
          {currentOption.description}
        </p>
      )}
    </Panel>
  )
}
