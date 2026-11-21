'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import { getChunkStrategyOption, isRetiredChunkStrategy } from '@/lib/chunk-strategies'

const STORAGE_KEY = 'mimirq_chunk_strategy'
const DEFAULT_CHUNK_STRATEGY = getChunkStrategyOption().value

type ChunkStrategyContextValue = {
  chunkStrategy: string
  setChunkStrategy: (value: string) => void
}

const ChunkStrategyContext = createContext<ChunkStrategyContextValue | null>(null)

export function ChunkStrategyProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [chunkStrategy, setChunkStrategy] = useState(DEFAULT_CHUNK_STRATEGY)
  const { capabilities, chunkStrategyAvailable } = usePipelineCapabilities()

  useEffect(() => {
    const stored = readClientStorage(STORAGE_KEY)
    if (stored) {
      setChunkStrategy(stored)
    }

    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && event.newValue) {
        setChunkStrategy(event.newValue)
      }
    }

    globalThis.window.addEventListener('storage', onStorage)
    return () => globalThis.window.removeEventListener('storage', onStorage)
  }, [])

  const persistChunkStrategy = useCallback((value: string) => {
    const strategy = value.trim().toLowerCase()
    const next = strategy === '' ? DEFAULT_CHUNK_STRATEGY : strategy
    setChunkStrategy(next)
    writeClientStorage(STORAGE_KEY, next)
  }, [])

  useEffect(() => {
    if (!capabilities || isRetiredChunkStrategy(chunkStrategy)) return
    if (chunkStrategyAvailable(chunkStrategy) === false) {
      persistChunkStrategy(capabilities.default_chunk_strategy)
    }
  }, [capabilities, chunkStrategy, chunkStrategyAvailable, persistChunkStrategy])

  const contextValue = useMemo(
    () => ({
      chunkStrategy,
      setChunkStrategy: persistChunkStrategy,
    }),
    [chunkStrategy, persistChunkStrategy],
  )

  return <ChunkStrategyContext.Provider value={contextValue}>{children}</ChunkStrategyContext.Provider>
}

export function useChunkStrategyPreference() {
  const context = useContext(ChunkStrategyContext)
  if (context === null) {
    throw new Error('useChunkStrategyPreference must be used within ChunkStrategyProvider')
  }
  return context
}
