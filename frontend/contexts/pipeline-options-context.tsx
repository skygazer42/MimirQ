'use client'

import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { DocumentPipelineOptions } from '@/types'

const STORAGE_KEY = 'mimirq_pipeline_options'

const DEFAULT_OPTIONS: DocumentPipelineOptions = {
  governance_enabled: false,
  chunk_size: 1000,
  chunk_overlap: 200,
  chunk_vector_enabled: true,
  bm25_index_enabled: true,
  sag_enabled: false,
  event_vector_enabled: true,
  entity_vector_enabled: true,
}

type PipelineOptionsState = {
  enabled: boolean
  options: DocumentPipelineOptions
}

type PipelineOptionsContextValue = {
  enabled: boolean
  options: DocumentPipelineOptions
  setEnabled: (value: boolean) => void
  updateOption: <K extends keyof DocumentPipelineOptions>(key: K, value: DocumentPipelineOptions[K]) => void
  reset: () => void
}

const PipelineOptionsContext = createContext<PipelineOptionsContextValue | null>(null)

const toBool = (value: unknown): boolean | undefined => {
  if (typeof value === 'boolean') return value
  return undefined
}

const toNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

const normalizeOptions = (raw: any): DocumentPipelineOptions => {
  if (!raw || typeof raw !== 'object') return { ...DEFAULT_OPTIONS }
  return {
    governance_enabled: toBool(raw.governance_enabled) ?? DEFAULT_OPTIONS.governance_enabled,
    chunk_size: toNumber(raw.chunk_size) ?? DEFAULT_OPTIONS.chunk_size,
    chunk_overlap: toNumber(raw.chunk_overlap) ?? DEFAULT_OPTIONS.chunk_overlap,
    chunk_vector_enabled: toBool(raw.chunk_vector_enabled) ?? DEFAULT_OPTIONS.chunk_vector_enabled,
    bm25_index_enabled: toBool(raw.bm25_index_enabled) ?? DEFAULT_OPTIONS.bm25_index_enabled,
    sag_enabled: toBool(raw.sag_enabled) ?? DEFAULT_OPTIONS.sag_enabled,
    event_vector_enabled: toBool(raw.event_vector_enabled) ?? DEFAULT_OPTIONS.event_vector_enabled,
    entity_vector_enabled: toBool(raw.entity_vector_enabled) ?? DEFAULT_OPTIONS.entity_vector_enabled,
  }
}

const normalizeState = (raw: any): PipelineOptionsState => {
  const enabled = typeof raw?.enabled === 'boolean' ? raw.enabled : false
  return {
    enabled,
    options: normalizeOptions(raw?.options),
  }
}

export function PipelineOptionsProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<PipelineOptionsState>({
    enabled: false,
    options: { ...DEFAULT_OPTIONS },
  })

  useEffect(() => {
    if (typeof window === 'undefined') return
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (!stored) return
    try {
      const parsed = JSON.parse(stored)
      setState(normalizeState(parsed))
    } catch {
      // ignore corrupted storage
    }
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, [state])

  useEffect(() => {
    if (typeof window === 'undefined') return
    const onStorage = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY || !event.newValue) return
      try {
        const parsed = JSON.parse(event.newValue)
        setState(normalizeState(parsed))
      } catch {
        // ignore
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const value = useMemo<PipelineOptionsContextValue>(() => ({
    enabled: state.enabled,
    options: state.options,
    setEnabled: (value) => {
      setState((prev) => ({ ...prev, enabled: value }))
    },
    updateOption: (key, value) => {
      setState((prev) => ({
        ...prev,
        options: {
          ...prev.options,
          [key]: value,
        },
      }))
    },
    reset: () => {
      setState({ enabled: false, options: { ...DEFAULT_OPTIONS } })
    },
  }), [state])

  return (
    <PipelineOptionsContext.Provider value={value}>
      {children}
    </PipelineOptionsContext.Provider>
  )
}

export function usePipelineOptions() {
  const ctx = useContext(PipelineOptionsContext)
  if (!ctx) {
    throw new Error('usePipelineOptions must be used within PipelineOptionsProvider')
  }
  return ctx
}
