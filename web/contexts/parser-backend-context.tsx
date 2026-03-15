'use client'

import { createContext, useContext, useEffect, useState } from 'react'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'

const STORAGE_KEY = 'mimirq_parser_backend'

type ParserBackendContextValue = {
  parserBackend: string
  setParserBackend: (value: string) => void
}

const ParserBackendContext = createContext<ParserBackendContextValue | null>(null)

export function ParserBackendProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [parserBackend, setParserBackendState] = useState('auto')
  const { capabilities, parserBackendAvailable } = usePipelineCapabilities()

  useEffect(() => {
    if (globalThis.window === undefined) return
    const stored = globalThis.window.localStorage.getItem(STORAGE_KEY)
    if (stored) {
      setParserBackendState(stored)
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && event.newValue) {
        setParserBackendState(event.newValue)
      }
    }
    globalThis.window.addEventListener('storage', handleStorage)
    return () => globalThis.window.removeEventListener('storage', handleStorage)
  }, [])

  const applyParserBackend = (value: string) => {
    const raw = (value || '').toLowerCase().trim()
    const normalized = raw.replaceAll("_", '-')
    let next = normalized
    if (next === 'magic-pdf') next = 'magicpdf'
    if (next === 'etl-4llm') next = 'etl4llm'
    if (next === 'bisheng-unstructured' || next === 'bishengunstructured' || next === 'bisheng') next = 'etl4llm'
    next = next || 'auto'
    setParserBackendState(next)
    if (globalThis.window !== undefined) {
      globalThis.window.localStorage.setItem(STORAGE_KEY, next)
    }
  }

  useEffect(() => {
    if (!capabilities) return
    const ok = parserBackendAvailable(parserBackend)
    if (ok === false) {
      applyParserBackend(capabilities.default_parser_backend || 'auto')
    }
  }, [capabilities, parserBackend, parserBackendAvailable])

  const setParserBackend = (value: string) => {
    applyParserBackend(value)
  }

  return (
    <ParserBackendContext.Provider
      value={{
        parserBackend,
        setParserBackend,
      }}
    >
      {children}
    </ParserBackendContext.Provider>
  )
}

export function useParserBackendPreference() {
  const ctx = useContext(ParserBackendContext)
  if (!ctx) {
    throw new Error('useParserBackendPreference must be used within ParserBackendProvider')
  }
  return ctx
}
