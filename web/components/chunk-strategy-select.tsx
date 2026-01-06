'use client'

import { cn } from '@/lib/utils'
import { CHUNK_STRATEGY_OPTIONS, getChunkStrategyOption, getStrategiesByGroup } from '@/lib/chunk-strategies'
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
}: ChunkStrategySelectProps) {
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { chunkStrategyAvailable } = usePipelineCapabilities()
  
  // 支持受控和非受控模式
  const currentValue = value ?? chunkStrategy
  const handleChange = onChange ?? setChunkStrategy
  const currentOption = getChunkStrategyOption(currentValue)

  const langchainStrategies = getStrategiesByGroup('langchain')
  const llamaIndexStrategies = getStrategiesByGroup('llama_index')
  const ragflowStrategies = getStrategiesByGroup('ragflow')

  return (
    <div
      className={cn(
        'flex flex-col gap-1 rounded-lg border border-gray-200 bg-white p-3',
        !compact && 'shadow-sm',
        className
      )}
    >
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span className="font-medium text-gray-700 flex items-center gap-1">
          <Layers className="w-3.5 h-3.5" />
          {label}
        </span>
        {currentOption.badge && (
          <span className="px-1.5 py-0.5 text-xs bg-indigo-100 text-indigo-700 rounded">
            {currentOption.badge}
          </span>
        )}
      </div>
      <select
        value={currentValue}
        onChange={(e) => handleChange(e.target.value)}
        className={cn(
          'mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200',
          compact && 'py-1.5 text-xs'
        )}
      >
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
        <optgroup label="RAGFlow">
          {ragflowStrategies.map((option) => (
            <option key={option.value} value={option.value} disabled={!!option.disabled || chunkStrategyAvailable(option.value) === false}>
              {option.label}
            </option>
          ))}
        </optgroup>
      </select>
      {!compact && (
        <p className="text-xs text-gray-500 leading-tight">{currentOption.description}</p>
      )}
    </div>
  )
}
