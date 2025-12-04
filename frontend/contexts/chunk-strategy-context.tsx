'use client'

import { createContext, useContext, useEffect, useState } from 'react'

const STORAGE_KEY = 'mimirq_chunk_strategy'

type ChunkStrategyContextValue = {
  chunkStrategy: string
  setChunkStrategy: (value: string) => void
}

const ChunkStrategyContext = createContext<ChunkStrategyContextValue | null>(null)

export function ChunkStrategyProvider({ children }: { children: React.ReactNode }) {
  const [chunkStrategy, setChunkStrategyState] = useState('langchain_recursive')

  useEffect(() => {
    if (typeof window === 'undefined') return
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored) {
      setChunkStrategyState(stored)
    }

    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && event.newValue) {
        setChunkStrategyState(event.newValue)
      }
    }

    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const setChunkStrategy = (value: string) => {
    setChunkStrategyState(value)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, value)
    }
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
