'use client'

import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { DocumentPipelineOptions } from '@/types'

const STORAGE_KEY = 'mimirq_pipeline_options'

const DEFAULT_OPTIONS: DocumentPipelineOptions = {
  governance_enabled: false,
  governance_remove_toc_lines: true,
  governance_remove_noise_lines: true,
  governance_unwrap_lines: true,
  governance_remove_common_lines: true,
  governance_remove_boilerplate: false,
  governance_remove_images: 'none',
  governance_pii_anonymize: false,
  governance_pii_mode: 'mask',
  governance_pii_mask: '[REDACTED]',
  governance_max_blank_lines: 1,
  governance_html_xpath: '',
  governance_drop_outline_only: false,
  governance_drop_outline_min_content_chars: 200,
  governance_drop_outline_max_heading_ratio: 0.85,
  governance_drop_low_density: false,
  governance_drop_low_density_threshold: 0.12,
  governance_unwrap_max_line_length: 120,
  governance_noise_min_chars: 2,
  governance_noise_ratio_threshold: 0.2,
  governance_common_lines_min_docs: 3,
  governance_common_lines_min_ratio: 0.35,
  chunk_size: 1000,
  chunk_overlap: 200,
  chunk_vector_enabled: true,
  bm25_index_enabled: true,
  kg_enabled: false,
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

const toInt = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

const toFloat = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number.parseFloat(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

const toString = (value: unknown): string | undefined => {
  if (typeof value === 'string') return value
  return undefined
}

const normalizeImageMode = (value: unknown): 'none' | 'decorative' | 'all' => {
  const v = (toString(value) || '').toLowerCase()
  if (v === 'decorative' || v === 'all' || v === 'none') return v
  return 'none'
}

const normalizePiiMode = (value: unknown): 'mask' | 'token' => {
  const v = (toString(value) || '').toLowerCase()
  if (v === 'token') return 'token'
  return 'mask'
}

const normalizeOptions = (raw: any): DocumentPipelineOptions => {
  if (!raw || typeof raw !== 'object') return { ...DEFAULT_OPTIONS }
  return {
    governance_enabled: toBool(raw.governance_enabled) ?? DEFAULT_OPTIONS.governance_enabled,
    governance_remove_toc_lines: toBool(raw.governance_remove_toc_lines) ?? DEFAULT_OPTIONS.governance_remove_toc_lines,
    governance_remove_noise_lines: toBool(raw.governance_remove_noise_lines) ?? DEFAULT_OPTIONS.governance_remove_noise_lines,
    governance_unwrap_lines: toBool(raw.governance_unwrap_lines) ?? DEFAULT_OPTIONS.governance_unwrap_lines,
    governance_remove_common_lines: toBool(raw.governance_remove_common_lines) ?? DEFAULT_OPTIONS.governance_remove_common_lines,
    governance_remove_boilerplate: toBool(raw.governance_remove_boilerplate) ?? DEFAULT_OPTIONS.governance_remove_boilerplate,
    governance_remove_images: normalizeImageMode(raw.governance_remove_images) ?? DEFAULT_OPTIONS.governance_remove_images,
    governance_pii_anonymize: toBool(raw.governance_pii_anonymize) ?? DEFAULT_OPTIONS.governance_pii_anonymize,
    governance_pii_mode: normalizePiiMode(raw.governance_pii_mode) ?? DEFAULT_OPTIONS.governance_pii_mode,
    governance_pii_mask: toString(raw.governance_pii_mask) ?? DEFAULT_OPTIONS.governance_pii_mask,
    governance_max_blank_lines: toInt(raw.governance_max_blank_lines) ?? DEFAULT_OPTIONS.governance_max_blank_lines,
    governance_html_xpath: toString(raw.governance_html_xpath) ?? DEFAULT_OPTIONS.governance_html_xpath,
    governance_drop_outline_only: toBool(raw.governance_drop_outline_only) ?? DEFAULT_OPTIONS.governance_drop_outline_only,
    governance_drop_outline_min_content_chars: toInt(raw.governance_drop_outline_min_content_chars) ?? DEFAULT_OPTIONS.governance_drop_outline_min_content_chars,
    governance_drop_outline_max_heading_ratio: toFloat(raw.governance_drop_outline_max_heading_ratio) ?? DEFAULT_OPTIONS.governance_drop_outline_max_heading_ratio,
    governance_drop_low_density: toBool(raw.governance_drop_low_density) ?? DEFAULT_OPTIONS.governance_drop_low_density,
    governance_drop_low_density_threshold: toFloat(raw.governance_drop_low_density_threshold) ?? DEFAULT_OPTIONS.governance_drop_low_density_threshold,
    governance_unwrap_max_line_length: toInt(raw.governance_unwrap_max_line_length) ?? DEFAULT_OPTIONS.governance_unwrap_max_line_length,
    governance_noise_min_chars: toInt(raw.governance_noise_min_chars) ?? DEFAULT_OPTIONS.governance_noise_min_chars,
    governance_noise_ratio_threshold: toFloat(raw.governance_noise_ratio_threshold) ?? DEFAULT_OPTIONS.governance_noise_ratio_threshold,
    governance_common_lines_min_docs: toInt(raw.governance_common_lines_min_docs) ?? DEFAULT_OPTIONS.governance_common_lines_min_docs,
    governance_common_lines_min_ratio: toFloat(raw.governance_common_lines_min_ratio) ?? DEFAULT_OPTIONS.governance_common_lines_min_ratio,
    chunk_size: toInt(raw.chunk_size) ?? DEFAULT_OPTIONS.chunk_size,
    chunk_overlap: toInt(raw.chunk_overlap) ?? DEFAULT_OPTIONS.chunk_overlap,
    chunk_vector_enabled: toBool(raw.chunk_vector_enabled) ?? DEFAULT_OPTIONS.chunk_vector_enabled,
    bm25_index_enabled: toBool(raw.bm25_index_enabled) ?? DEFAULT_OPTIONS.bm25_index_enabled,
    kg_enabled: toBool(raw.kg_enabled) ?? DEFAULT_OPTIONS.kg_enabled,
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
