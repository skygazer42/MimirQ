'use client'

import { useTranslations } from 'next-intl'

import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { readPipelineOptionsImport } from '@/lib/document-pipeline-options'
import type { JsonObject } from '@/types/common'
import type { DocumentPipelineOptions } from '@/types/processing'

import { useChunkPreview } from './context'
import { isJsonObject } from './utils/metadata'
import { encodeSeparatorInput } from './utils/separators'

type ConfigImportResult = { ok: true } | { ok: false; error: string }

function readConfigNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value !== 'string' || value.trim().length === 0) return undefined

  const number = Number(value)
  return Number.isFinite(number) ? number : undefined
}

function readConfigInteger(value: unknown, min: number, max: number): number | undefined {
  const number = readConfigNumber(value)
  return number === undefined ? undefined : Math.max(min, Math.min(max, Math.trunc(number)))
}

export function useChunkPreviewConfig(source: 'workbench' | 'preset') {
  const {
    buildChunkPreviewRequestParams,
    separatorCustom,
    setDatasetId,
    setParserBackend,
    updateSettings,
    updateSeparatorSettings,
    updateParentChildSettings,
  } = useChunkPreview()
  const pipelineContext = usePipelineOptions()
  const t = useTranslations('ChunkPreview')

  function buildConfig(): JsonObject {
    const params = buildChunkPreviewRequestParams()
    const separator =
      params.separator_preset === 'custom' && source === 'workbench' ? separatorCustom : params.separator
    return {
      dataset_id: params.dataset_id ?? null,
      chunk_size: params.chunk_size,
      chunk_overlap: params.chunk_overlap,
      parser_backend: params.parser_backend,
      chunk_strategy: params.chunk_strategy,
      child_ratio: params.child_ratio,
      min_child_size: params.min_child_size,
      separator_preset: params.separator_preset,
      separator,
      keep_separator: params.keep_separator,
      separator_max_chunk_size: params.separator_max_chunk_size,
      pipeline: params.pipeline ?? null,
    }
  }

  function applyConfig(config: unknown): ConfigImportResult {
    if (!isJsonObject(config)) return { ok: false, error: t('topBar.toasts.invalidJsonObject') }

    const pipeline = config.pipeline
    let preparedPipeline: { options: DocumentPipelineOptions; enabled?: boolean } | undefined
    if (pipeline !== undefined && pipeline !== null) {
      if (!isJsonObject(pipeline)) return { ok: false, error: t('topBar.toasts.invalidPipelineConfig') }

      const result = readPipelineOptionsImport(
        source === 'preset' ? pipeline : { enabled: true, options: { ...pipelineContext.options, ...pipeline } },
      )
      if (!result.ok) return result
      preparedPipeline = result
    }

    if (typeof config.dataset_id === 'string') setDatasetId(config.dataset_id)
    else if (config.dataset_id === null) setDatasetId('')

    if (typeof config.parser_backend === 'string') setParserBackend(config.parser_backend)

    if (preparedPipeline !== undefined) {
      pipelineContext.applyOptions(preparedPipeline.options, preparedPipeline.enabled ?? true)
    } else if (pipeline === null) {
      pipelineContext.setEnabled(false)
    }

    updateSettings({
      strategy:
        typeof config.chunk_strategy === 'string' && config.chunk_strategy.length > 0
          ? config.chunk_strategy
          : undefined,
      chunkSize: readConfigInteger(config.chunk_size, 50, 4000),
      chunkOverlap: readConfigInteger(config.chunk_overlap, 0, 1000),
    })
    let separator: string | undefined
    if (typeof config.separator === 'string') {
      separator = source === 'preset' ? encodeSeparatorInput(config.separator) : config.separator
    }
    updateSeparatorSettings({
      separatorPreset: typeof config.separator_preset === 'string' ? config.separator_preset : undefined,
      separatorCustom: separator,
      keepSeparator: typeof config.keep_separator === 'boolean' ? config.keep_separator : undefined,
      separatorMaxChunkSize: readConfigInteger(config.separator_max_chunk_size, 0, 20000),
    })
    updateParentChildSettings({
      parentChildRatio: readConfigNumber(config.child_ratio),
      parentChildMinChildSize: readConfigNumber(config.min_child_size),
    })

    return { ok: true }
  }

  return { buildConfig, applyConfig }
}
