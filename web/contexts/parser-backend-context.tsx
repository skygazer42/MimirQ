'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import { isRetiredParserBackend, normalizeParserBackendName } from '@/lib/parser-compat'

const STORAGE_KEY = 'mimirq_parser_backend'

type ParserBackendContextValue = {
  parserBackend: string
  setParserBackend: (value: string) => void
}

const ParserBackendContext = createContext<ParserBackendContextValue | null>(null)

export function ParserBackendProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [parserBackend, setParserBackend] = useState(() => normalizeParserBackendName())
  const { capabilities, parserBackendAvailable } = usePipelineCapabilities()

  useEffect(() => {
    const stored = readClientStorage(STORAGE_KEY)
    if (stored) {
      setParserBackend(normalizeParserBackendName(stored))
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && event.newValue) {
        setParserBackend(normalizeParserBackendName(event.newValue))
      }
    }
    globalThis.window.addEventListener('storage', handleStorage)
    return () => globalThis.window.removeEventListener('storage', handleStorage)
  }, [])

  const persistParserBackend = useCallback((value: string) => {
    const next = normalizeParserBackendName(value)
    setParserBackend(next)
    writeClientStorage(STORAGE_KEY, next)
  }, [])

  useEffect(() => {
    if (!capabilities || isRetiredParserBackend(parserBackend)) return
    if (parserBackendAvailable(parserBackend) === false) {
      persistParserBackend(capabilities.default_parser_backend)
    }
  }, [capabilities, parserBackend, parserBackendAvailable, persistParserBackend])

  const contextValue = useMemo(
    () => ({
      parserBackend,
      setParserBackend: persistParserBackend,
    }),
    [parserBackend, persistParserBackend],
  )

  return <ParserBackendContext.Provider value={contextValue}>{children}</ParserBackendContext.Provider>
}

export function useParserBackendPreference() {
  const context = useContext(ParserBackendContext)
  if (context === null) {
    throw new Error('useParserBackendPreference must be used within ParserBackendProvider')
  }
  return context
}
