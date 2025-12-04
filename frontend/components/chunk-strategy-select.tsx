'use client'

import { cn } from '@/lib/utils'
import { CHUNK_STRATEGY_OPTIONS, getChunkStrategyOption } from '@/lib/chunk-strategies'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { Layers } from 'lucide-react'

interface ChunkStrategySelectProps {
  label?: string
  className?: string
  compact?: boolean
}

export function ChunkStrategySelect({
  label = '切块方式',
  className,
  compact = false,
}: ChunkStrategySelectProps) {
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const currentOption = getChunkStrategyOption(chunkStrategy)

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
      </div>
      <select
        value={chunkStrategy}
        onChange={(e) => setChunkStrategy(e.target.value)}
        className={cn(
          'mt-1 w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200',
          compact && 'py-1.5 text-xs'
        )}
      >
        {CHUNK_STRATEGY_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {!compact && (
        <p className="text-xs text-gray-500 leading-tight">{currentOption.description}</p>
      )}
    </div>
  )
}
