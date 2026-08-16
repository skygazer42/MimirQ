'use client'

import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { DocumentPipelineOptions } from '@/types'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import {
  DEFAULT_DOCUMENT_PIPELINE_OPTIONS,
  normalizeDocumentPipelineOptions,
} from '@/lib/document-pipeline-options'

const STORAGE_KEY = 'mimirq_pipeline_options'

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
  exportJson: () => string
  importJson: (jsonText: string) => { ok: boolean; error?: string }
}

const PipelineOptionsContext = createContext<PipelineOptionsContextValue | null>(null)

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

const normalizeState = (raw: unknown): PipelineOptionsState => {
  const record =
    raw && typeof raw === 'object' && !Array.isArray(raw)
      ? (raw as Record<string, unknown>)
      : {}
  const enabled = typeof record.enabled === 'boolean' ? record.enabled : false
  return {
    enabled,
    options: normalizeDocumentPipelineOptions(record.options),
  }
}

export function PipelineOptionsProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [state, setState] = useState<PipelineOptionsState>({
    enabled: false,
    options: { ...DEFAULT_DOCUMENT_PIPELINE_OPTIONS },
  })

  useEffect(() => {
    const stored = readClientStorage(STORAGE_KEY)
    if (!stored) return
    try {
      const parsed = JSON.parse(stored)
      setState(normalizeState(parsed))
    } catch {
      // ignore corrupted storage
    }
  }, [])

  useEffect(() => {
    writeClientStorage(STORAGE_KEY, JSON.stringify(state))
  }, [state])

  useEffect(() => {
    if (globalThis.window === undefined) return
    const onStorage = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY || !event.newValue) return
      try {
        const parsed = JSON.parse(event.newValue)
        setState(normalizeState(parsed))
      } catch {
        // ignore
      }
    }
    globalThis.window.addEventListener('storage', onStorage)
    return () => globalThis.window.removeEventListener('storage', onStorage)
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
      setState({
        enabled: false,
        options: { ...DEFAULT_DOCUMENT_PIPELINE_OPTIONS },
      })
    },
    exportJson: () => JSON.stringify({ enabled: state.enabled, options: state.options }, null, 2),
    importJson: (jsonText: string) => {
      const raw = (jsonText || '').trim()
      if (!raw) return { ok: false, error: 'Empty JSON' }
      let parsed: unknown
      try {
        parsed = JSON.parse(raw)
      } catch {
        return { ok: false, error: 'Invalid JSON' }
      }

      // Accept either:
      // - { enabled, options }
      // - { ...options }
      try {
        if (isRecord(parsed) && ('options' in parsed || 'enabled' in parsed)) {
          const enabled =
            typeof parsed.enabled === 'boolean' ? parsed.enabled : state.enabled
          const optionsRaw = parsed.options ?? {}
          setState({
            enabled,
            options: normalizeDocumentPipelineOptions(optionsRaw),
          })
          return { ok: true }
        }

        setState((prev) => ({
          ...prev,
          options: normalizeDocumentPipelineOptions(parsed),
        }))
        return { ok: true }
      } catch {
        return { ok: false, error: 'Invalid options shape' }
      }
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
