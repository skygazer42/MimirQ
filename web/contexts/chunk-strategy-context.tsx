'use client'

import { createContext, useContext, useEffect, useState } from 'react'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'

const STORAGE_KEY = 'mimirq_chunk_strategy'

type ChunkStrategyContextValue = {
  chunkStrategy: string
  setChunkStrategy: (value: string) => void
}

const ChunkStrategyContext = createContext<ChunkStrategyContextValue | null>(null)

export function ChunkStrategyProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [chunkStrategy, setChunkStrategyState] = useState('langchain_recursive')
  const { capabilities, chunkStrategyAvailable } = usePipelineCapabilities()

  useEffect(() => {
    if (typeof globalThis.window === 'undefined') return
    const stored = globalThis.window.localStorage.getItem(STORAGE_KEY)
    if (stored) {
      setChunkStrategyState(stored)
    }

    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && event.newValue) {
        setChunkStrategyState(event.newValue)
      }
    }

    globalThis.window.addEventListener('storage', onStorage)
    return () => globalThis.window.removeEventListener('storage', onStorage)
  }, [])

  const applyChunkStrategy = (value: string) => {
    const next = (value || '').trim().toLowerCase() || 'langchain_recursive'
    setChunkStrategyState(next)
    if (typeof globalThis.window !== 'undefined') {
      globalThis.window.localStorage.setItem(STORAGE_KEY, next)
    }
  }

  useEffect(() => {
    if (!capabilities) return
    const ok = chunkStrategyAvailable(chunkStrategy)
    if (ok === false) {
      applyChunkStrategy(capabilities.default_chunk_strategy || 'langchain_recursive')
    }
  }, [capabilities, chunkStrategy, chunkStrategyAvailable])

  const setChunkStrategy = (value: string) => {
    applyChunkStrategy(value)
  }

  return (
    <ChunkStrategyContext.Provider
      value={{
        chunkStrategy,
        setChunkStrategy,
      }}
    >
      {children}
    </ChunkStrategyContext.Provider>
  )
}

export function useChunkStrategyPreference() {
  const ctx = useContext(ChunkStrategyContext)
  if (!ctx) {
    throw new Error('useChunkStrategyPreference must be used within ChunkStrategyProvider')
  }
  return ctx
}
