'use client'

import { cn } from '@/lib/utils'
import { getChunkStrategyOption, getStrategiesByGroup } from '@/lib/chunk-strategies'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { Layers } from 'lucide-react'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'

interface ChunkStrategySelectProps {
  label?: string
  className?: string
  compact?: boolean
  value?: string
  onChange?: (value: string) => void
}

export function ChunkStrategySelect({
  label = '切块方式',
  className,
  compact = false,
  value,
  onChange,
}: Readonly<ChunkStrategySelectProps>) {
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { chunkStrategyAvailable } = usePipelineCapabilities()
  
  // 支持受控和非受控模式
  const currentValue = value ?? chunkStrategy
  const handleChange = onChange ?? setChunkStrategy
  const currentOption = getChunkStrategyOption(currentValue)

  const presetStrategies = getStrategiesByGroup('preset')
  const langchainStrategies = getStrategiesByGroup('langchain')
  const llamaIndexStrategies = getStrategiesByGroup('llama_index')
  const integratedStrategies = getStrategiesByGroup('integrated')

  return (
    <div
      className={cn(
        'flex flex-col gap-1 rounded-lg border border-border bg-card p-3',
        !compact && 'shadow-sm',
        className
      )}
    >
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span className="font-medium text-foreground flex items-center gap-1">
          <Layers className="w-3.5 h-3.5" />
          {label}
        </span>
        {currentOption.badge && (
          <span className="px-1.5 py-0.5 text-[11px] bg-primary/10 text-primary rounded border border-primary/20 font-semibold">
            {currentOption.badge}
          </span>
        )}
      </div>
      <select
        value={currentValue}
        onChange={(e) => handleChange(e.target.value)}
        className={cn(
          'mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 motion-reduce:transition-none',
          compact && 'py-1.5 text-xs'
        )}
      >
        <optgroup label="预设">
          {presetStrategies.map((option) => (
            <option
              key={option.value}
              value={option.value}
              disabled={
                !!option.disabled || chunkStrategyAvailable(option.value) === false
              }
            >
              {option.label}
            </option>
          ))}
        </optgroup>
        <optgroup label="LangChain">
          {langchainStrategies.map((option) => (
            <option key={option.value} value={option.value} disabled={!!option.disabled || chunkStrategyAvailable(option.value) === false}>
              {option.label}
            </option>
          ))}
        </optgroup>
        <optgroup label="LlamaIndex">
          {llamaIndexStrategies.map((option) => (
            <option key={option.value} value={option.value} disabled={!!option.disabled || chunkStrategyAvailable(option.value) === false}>
              {option.label}
            </option>
          ))}
        </optgroup>
        <optgroup label="Integrated pipeline">
          {integratedStrategies.map((option) => (
            <option key={option.value} value={option.value} disabled={!!option.disabled || chunkStrategyAvailable(option.value) === false}>
              {option.label}
            </option>
          ))}
        </optgroup>
      </select>
      {!compact && (
        <p className="text-xs text-muted-foreground leading-tight">{currentOption.description}</p>
      )}
    </div>
  )
}
