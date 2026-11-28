'use client'

import { useId, useState } from 'react'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { PARSER_BACKEND_OPTIONS, getParserOption, type ParserBackendOption } from '@/lib/parser-options'
import { buildChunkStrategyCatalog, getChunkStrategyOption, type ChunkStrategyOption } from '@/lib/chunk-strategies'
import { normalizeParserBackendName } from '@/lib/parser-compat'
import {
  FileText,
  Cpu,
  LayoutGrid,
  Cloud,
  ScanLine,
  ScanText,
  FileCode,
  Layers,
  Hash,
  AlignLeft,
  GitBranch,
  ChevronRight,
  Check,
  type PlatformIcon,
} from '@/components/icons'
import { cn } from '@/lib/utils'
import styles from '../settings.module.css'

type FrontendPreferencesSectionProps = {
  parserBackend: string
  setParserBackend: (value: string) => void
  chunkStrategy: string
  setChunkStrategy: (value: string) => void
}

const PARSER_ICONS: Record<ParserBackendOption['icon'], PlatformIcon> = {
  auto: FileText,
  basic: FileText,
  docling: Cpu,
  layout: LayoutGrid,
  mineru: Cloud,
  deepdoc: ScanLine,
  deepseekocr: ScanText,
  markitdown: FileCode,
  magicpdf: LayoutGrid,
}
const CHUNK_ICONS: Record<ChunkStrategyOption['icon'], PlatformIcon> = {
  recursive: Layers,
  token: Hash,
  sentence: AlignLeft,
  separator: AlignLeft,
  hierarchical: GitBranch,
  integrated: Layers,
}
const PARSER_DESCRIPTIONS: Record<string, string> = {
  docling: '结构感知解析，可提取 PDF 结构与表格',
  marker: '将 PDF 转为 Markdown，可保留图片引用',
  etl4llm: '识别版面、表格与图片，需要自建服务',
  paddle_vl: '扫描件 PDF 的 OCR 与版面解析',
}

type PipelineChoice = {
  value: string
  label: string
  description: string
  icon: PlatformIcon
  unavailable?: { label: '待确认' | '不可用'; reason: string }
}

function PipelineChoiceList({
  label,
  choices,
  value,
  onChange,
}: Readonly<{
  label: string
  choices: PipelineChoice[]
  value: string
  onChange: (value: string) => void
}>) {
  const name = useId()
  const availableChoices = choices.filter((choice) => !choice.unavailable)
  const firstChoices = availableChoices.slice(0, 6)
  const unavailableChoices = choices.filter((choice) => choice.unavailable)
  const additionalChoices = [...availableChoices.slice(6), ...unavailableChoices]
  const [expanded, setExpanded] = useState<boolean>()
  const showAdditionalChoices = expanded ?? additionalChoices.some((choice) => choice.value === value)
  const renderChoice = (choice: PipelineChoice) => {
    const selected = choice.value === value
    const isUnavailable = choice.unavailable !== undefined
    const Icon = choice.icon
    return (
      <label
        key={choice.value}
        className={styles.choice}
        data-selected={selected}
        data-disabled={isUnavailable}
        title={choice.unavailable?.reason}
      >
        <input
          className="sr-only"
          type="radio"
          name={name}
          value={choice.value}
          checked={selected}
          disabled={isUnavailable}
          onChange={() => onChange(choice.value)}
        />
        <Icon className="size-[18px] shrink-0" />
        <span className={styles.choiceCopy}>
          <span className={styles.choiceName}>
            {choice.label}
            {choice.value === 'auto' && !choice.label.includes('推荐') ? (
              <span className={styles.recommended}>推荐</span>
            ) : null}
          </span>
          <span className={cn(styles.choiceDescription, 'block')}>{choice.description}</span>
          {choice.unavailable ? (
            <span className={cn(styles.choiceDescription, 'block')}>{choice.unavailable.reason}</span>
          ) : null}
        </span>
        {choice.unavailable ? (
          <span className={styles.availability}>{choice.unavailable.label}</span>
        ) : selected ? (
          <Check className="size-[18px] shrink-0" />
        ) : null}
      </label>
    )
  }
  return (
    <div role="radiogroup" aria-label={label} className={styles.choices}>
      {firstChoices.map(renderChoice)}
      {additionalChoices.length > 0 ? (
        <details
          className={styles.more}
          open={showAdditionalChoices}
          onToggle={(event) => setExpanded(event.currentTarget.open)}
        >
          <summary className={cn(styles.moreSummary, 'focus-ring')}>
            <span>
              {unavailableChoices.length > 0 ? '更多与暂不可用的' : '更多'}
              {label}（{additionalChoices.length}）
            </span>
            <ChevronRight className={cn(styles.advancedChevron, 'size-3.5')} />
          </summary>
          {label === '解析方式' && unavailableChoices.length > 0 ? (
            <p className={styles.moreHint}>可在「解析服务」中启用解析器；待确认的选项需先读取可用状态。</p>
          ) : null}
          {additionalChoices.map(renderChoice)}
        </details>
      ) : null}
    </div>
  )
}

export function FrontendPreferencesSection({
  parserBackend,
  setParserBackend,
  chunkStrategy,
  setChunkStrategy,
}: Readonly<FrontendPreferencesSectionProps>) {
  const [inspector, setInspector] = useState<'parser' | 'chunk'>('parser')
  const { capabilities, loading, error, refresh, parserBackendAvailable } = usePipelineCapabilities()
  const selectedParser = getParserOption(parserBackend)
  const ParserIcon = PARSER_ICONS[selectedParser.icon]
  const catalog = buildChunkStrategyCatalog(capabilities?.chunk_strategies)
  const normalizedChunkStrategy = chunkStrategy.trim().toLowerCase()
  const selectedChunk =
    catalog.find((choice) => choice.value === normalizedChunkStrategy) ?? getChunkStrategyOption(chunkStrategy)
  const ChunkIcon = CHUNK_ICONS[selectedChunk.icon]
  const parserChoices: PipelineChoice[] = PARSER_BACKEND_OPTIONS.map((option) => {
    const choice = {
      ...option,
      description: PARSER_DESCRIPTIONS[option.value] ?? option.description,
      icon: PARSER_ICONS[option.icon],
    }
    if (option.value === 'auto' || option.value === 'basic') return choice

    const available = parserBackendAvailable(option.value)
    if (available) return choice
    if (available === undefined) {
      return { ...choice, unavailable: { label: '待确认', reason: '尚未读取到该解析器的可用状态' } }
    }

    const notes = capabilities?.pdf_backends
      .find((item) => normalizeParserBackendName(item.name) === option.value)
      ?.notes?.trim()
    return {
      ...choice,
      unavailable: { label: '不可用', reason: notes ? notes : '此解析器暂不可用' },
    }
  })
  const chunkChoices: PipelineChoice[] = catalog.map((option) => ({
    ...option,
    icon: CHUNK_ICONS[option.icon],
    unavailable:
      option.disabled === true || option.available === false
        ? { label: '不可用', reason: '当前无法使用此切块策略' }
        : undefined,
  }))

  return (
    <div className={styles.preferences}>
      <div className={styles.current}>
        <p className={styles.regionTitle}>当前配置</p>
        <div className={styles.field}>
          <span className={styles.fieldLabel}>解析方式</span>
          <button
            type="button"
            aria-label="选择解析方式"
            aria-pressed={inspector === 'parser'}
            aria-controls="settings-pipeline-inspector"
            className={cn(styles.value, 'focus-ring')}
            onClick={() => setInspector('parser')}
          >
            <ParserIcon className="size-[18px] shrink-0" />
            <span className={styles.valueCopy}>{selectedParser.label}</span>
            <ChevronRight className="size-3.5 shrink-0" />
          </button>
        </div>
        <div className={styles.field}>
          <span className={styles.fieldLabel}>切块策略</span>
          <button
            type="button"
            aria-label="选择切块策略"
            aria-pressed={inspector === 'chunk'}
            aria-controls="settings-pipeline-inspector"
            className={cn(styles.value, 'focus-ring')}
            onClick={() => setInspector('chunk')}
          >
            <ChunkIcon className="size-[18px] shrink-0" />
            <span className={styles.valueCopy}>{selectedChunk.label}</span>
            <ChevronRight className="size-3.5 shrink-0" />
          </button>
          <p className={styles.note}>
            {chunkStrategy === 'langchain_recursive'
              ? '按段落、句号等分隔符递归切分，保留语义完整性。'
              : selectedChunk.description}
          </p>
        </div>
        <details className={styles.advanced}>
          <summary className={cn(styles.advancedSummary, 'focus-ring')}>
            <ChevronRight className={cn(styles.advancedChevron, 'mt-1 size-3.5 shrink-0')} />
            <span>
              <span className="block">管线高级选项</span>
              <span className={cn(styles.advancedNote, 'block')}>合并切块、重叠与内容预处理</span>
            </span>
          </summary>
          <div className={styles.advancedContent}>
            <PipelineOptionsPanel compact />
          </div>
        </details>
      </div>
      <section
        id="settings-pipeline-inspector"
        aria-label={inspector === 'parser' ? '解析方式选项' : '切块策略选项'}
        className={styles.inspector}
      >
        <h3 className={styles.inspectorHeader}>{inspector === 'parser' ? '解析方式' : '切块策略'}</h3>
        {loading && !capabilities ? (
          <p role="status" className={styles.inspectorStatus}>
            正在读取可用选项…
          </p>
        ) : null}
        {error ? (
          <p role="alert" className={cn(styles.inspectorStatus, 'text-destructive')}>
            无法读取解析能力。
            <button type="button" className={cn(styles.retry, 'focus-ring')} onClick={() => void refresh()}>
              重试
            </button>
          </p>
        ) : null}
        {inspector === 'parser' ? (
          <PipelineChoiceList
            key="parser"
            label="解析方式"
            choices={parserChoices}
            value={selectedParser.value}
            onChange={setParserBackend}
          />
        ) : (
          <PipelineChoiceList
            key="chunk"
            label="切块策略"
            choices={chunkChoices}
            value={selectedChunk.value}
            onChange={setChunkStrategy}
          />
        )}
      </section>
    </div>
  )
}
