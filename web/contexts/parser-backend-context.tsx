'use client'

import { createContext, useContext, useEffect, useState } from 'react'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'

const STORAGE_KEY = 'mimirq_parser_backend'

type ParserBackendContextValue = {
  parserBackend: string
  setParserBackend: (value: string) => void
}

const ParserBackendContext = createContext<ParserBackendContextValue | null>(null)

export function ParserBackendProvider({ children }: { children: React.ReactNode }) {
  const [parserBackend, setParserBackendState] = useState('auto')
  const { capabilities, parserBackendAvailable } = usePipelineCapabilities()

  useEffect(() => {
    if (typeof window === 'undefined') return
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored) {
      setParserBackendState(stored)
    }

    const handleStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && event.newValue) {
        setParserBackendState(event.newValue)
      }
    }
    window.addEventListener('storage', handleStorage)
    return () => window.removeEventListener('storage', handleStorage)
  }, [])

  const applyParserBackend = (value: string) => {
    const raw = (value || '').toLowerCase().trim()
    const normalized = raw.replace(/_/g, '-')
    const next = (normalized === 'magic-pdf' ? 'magicpdf' : normalized) || 'auto'
    setParserBackendState(next)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, next)
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
