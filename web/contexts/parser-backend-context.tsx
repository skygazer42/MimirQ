'use client'

import { createContext, useContext, useEffect, useState } from 'react'

const STORAGE_KEY = 'mimirq_parser_backend'

type ParserBackendContextValue = {
  parserBackend: string
  setParserBackend: (value: string) => void
}

const ParserBackendContext = createContext<ParserBackendContextValue | null>(null)

export function ParserBackendProvider({ children }: { children: React.ReactNode }) {
  const [parserBackend, setParserBackendState] = useState('auto')

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

  const setParserBackend = (value: string) => {
    setParserBackendState(value)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STORAGE_KEY, value)
    }
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
