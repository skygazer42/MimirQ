'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import type { DocumentPipelineOptions } from '@/types'
import { readClientStorage, writeClientStorage } from '@/lib/client-storage'
import {
  DEFAULT_DOCUMENT_PIPELINE_OPTIONS,
  getUnsupportedDocumentPipelineOptionKeys,
  normalizeDocumentPipelineOptions,
  readPipelineOptionsImport,
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
  applyOptions: (options: DocumentPipelineOptions, enabled?: boolean) => void
  updateOption: <K extends keyof DocumentPipelineOptions>(key: K, value: DocumentPipelineOptions[K]) => void
  reset: () => void
  exportJson: () => string
  importJson: (jsonText: string) => { ok: true } | { ok: false; error: string }
}

const PipelineOptionsContext = createContext<PipelineOptionsContextValue | null>(null)

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function normalizeState(raw: Record<string, unknown>): PipelineOptionsState {
  return {
    enabled:
      raw.enabled === true &&
      isRecord(raw.options) &&
      getUnsupportedDocumentPipelineOptionKeys(raw.options).length === 0,
    options: normalizeDocumentPipelineOptions(raw.options),
  }
}

export function PipelineOptionsProvider({ children }: Readonly<{ children: ReactNode }>) {
  const [state, setState] = useState<PipelineOptionsState>({
    enabled: false,
    options: { ...DEFAULT_DOCUMENT_PIPELINE_OPTIONS },
  })
  const [storageLoaded, setStorageLoaded] = useState(false)

  useEffect(() => {
    function restoreOptions(json: string) {
      let parsed: unknown
      try {
        parsed = JSON.parse(json)
      } catch {
        return
      }

      if (!isRecord(parsed)) return
      const restored = normalizeState(parsed)
      if (parsed.enabled === true && !restored.enabled) {
        toast.error('旧管线配置无效，已清理并关闭覆盖，请检查后重新启用', { id: STORAGE_KEY })
      }
      setState(restored)
    }

    const stored = readClientStorage(STORAGE_KEY)
    if (stored !== null) restoreOptions(stored)
    setStorageLoaded(true)

    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY && event.newValue !== null) restoreOptions(event.newValue)
    }
    globalThis.window.addEventListener('storage', onStorage)
    return () => globalThis.window.removeEventListener('storage', onStorage)
  }, [])

  useEffect(() => {
    if (!storageLoaded) return
    writeClientStorage(STORAGE_KEY, JSON.stringify(state))
  }, [state, storageLoaded])

  const applyOptions = useCallback((options: DocumentPipelineOptions, enabled?: boolean) => {
    setState((current) => ({ options, enabled: enabled ?? current.enabled }))
  }, [])

  const value = useMemo<PipelineOptionsContextValue>(
    () => ({
      enabled: state.enabled,
      options: state.options,
      applyOptions,
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
        const raw = jsonText.trim()
        if (!raw) return { ok: false, error: 'Empty JSON' }
        let parsed: unknown
        try {
          parsed = JSON.parse(raw)
        } catch {
          return { ok: false, error: 'Invalid JSON' }
        }

        const result = readPipelineOptionsImport(parsed)
        if (!result.ok) return result
        applyOptions(result.options, result.enabled)
        return { ok: true }
      },
    }),
    [applyOptions, state],
  )

  return <PipelineOptionsContext.Provider value={value}>{children}</PipelineOptionsContext.Provider>
}

export function usePipelineOptions() {
  const ctx = useContext(PipelineOptionsContext)
  if (ctx === null) {
    throw new Error('usePipelineOptions must be used within PipelineOptionsProvider')
  }
  return ctx
}
