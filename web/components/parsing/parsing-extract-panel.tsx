'use client'

import { useId, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type FormEvent } from 'react'
import { ChevronDown, ChevronUp, FileSearch, WandSparkles } from '@/components/icons'

import { parsingApi } from '@/lib/api/parsing'
import type {
  ParsingElement,
  ParsingExtractEvidence,
  ParsingExtractFieldSpec,
  ParsingExtractRequest,
  ParsingExtractResponse,
} from '@/lib/api/parsing'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { cn } from '@/lib/utils'
import { formatParsingPages, getParsingElementVisualKind, getParsingPages } from '@/lib/parsing-elements'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { LoadingButton } from '@/components/ui/loading-button'
import { Textarea } from '@/components/ui/textarea'
import styles from './parsing-compare.module.css'

export type ParsingEvidenceSelection = Readonly<{
  fieldName: string
  evidence: ParsingExtractEvidence
}>

type ParsingExtractPanelProps = Readonly<{
  documentId?: string | null
  activeElements: readonly ParsingElement[]
  onSelectEvidence: (selection: ParsingEvidenceSelection) => void
  className?: string
}>

type ExtractionMode = ParsingExtractRequest['mode']
type ExtractionDraft = {
  fieldName: string
  sourceKind: string
  sourceVisualKind: string
  aliases: string
  prompt: string
}
type ExtractionResult = {
  response: ParsingExtractResponse
  fingerprint: string
}

const SOURCE_KIND_LABELS = new Map([
  ['heading', '标题'],
  ['paragraph', '正文'],
  ['list', '列表'],
  ['table', '表格'],
  ['image', '图片'],
  ['equation', '公式'],
  ['seal', '印章'],
  ['unknown', '未知类型'],
])

function suggestDefaults(elements: readonly ParsingElement[]): ExtractionDraft {
  const imageVisualKinds = new Set(
    elements
      .filter((item) => item.kind === 'image')
      .map(getParsingElementVisualKind)
      .filter((kind): kind is string => kind !== null && kind.length > 0),
  )
  const hasSeal = elements.some((item) => item.kind === 'seal')
  if (hasSeal) {
    return {
      fieldName: 'company_name',
      sourceKind: 'seal',
      sourceVisualKind: '',
      aliases: '公司, 公章',
      prompt: '提取主印章对应的主体名称',
    }
  }
  const hasEquation = elements.some((item) => item.kind === 'equation')
  if (hasEquation) {
    return {
      fieldName: 'main_formula',
      sourceKind: 'equation',
      sourceVisualKind: '',
      aliases: '公式',
      prompt: '提取主要公式',
    }
  }
  if (imageVisualKinds.has('chart')) {
    return {
      fieldName: 'chart_summary',
      sourceKind: 'image',
      sourceVisualKind: 'chart',
      aliases: '图表, chart',
      prompt: '提取主要图表说明',
    }
  }
  if (imageVisualKinds.has('qr')) {
    return {
      fieldName: 'qr_text',
      sourceKind: 'image',
      sourceVisualKind: 'qr',
      aliases: '二维码, QR',
      prompt: '提取二维码对应的文本或说明',
    }
  }
  if (imageVisualKinds.has('barcode')) {
    return {
      fieldName: 'barcode_text',
      sourceKind: 'image',
      sourceVisualKind: 'barcode',
      aliases: '条码, barcode',
      prompt: '提取条码对应的文本或说明',
    }
  }
  if (imageVisualKinds.has('diagram')) {
    return {
      fieldName: 'diagram_summary',
      sourceKind: 'image',
      sourceVisualKind: 'diagram',
      aliases: '示意图, diagram',
      prompt: '提取主要示意图说明',
    }
  }
  return {
    fieldName: 'primary_text',
    sourceKind: '',
    sourceVisualKind: '',
    aliases: '',
    prompt: '提取当前文档最重要的字段',
  }
}

function parseAliases(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[,\n，]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  )
}

function formatBbox(bbox: NonNullable<ParsingElement['bbox']>): string {
  return `${bbox.x0},${bbox.y0},${bbox.x1},${bbox.y1}`
}

function buildExtractionRequest(mode: ExtractionMode, draft: ExtractionDraft): ParsingExtractRequest {
  const field: ParsingExtractFieldSpec = { type: 'string', aliases: parseAliases(draft.aliases) }
  const sourceKind = draft.sourceKind.trim()
  const sourceVisualKind = draft.sourceVisualKind.trim()
  if (sourceKind.length > 0) field.source_kind = sourceKind
  if (sourceVisualKind.length > 0) field.source_visual_kind = sourceVisualKind
  const fieldName = draft.fieldName.trim()
  if (mode === 'schema') return { mode, schema_: { [fieldName]: field }, max_evidence: 3 }
  return { mode, prompt: draft.prompt.trim(), field_hints: { [fieldName]: field }, max_evidence: 3 }
}

function getSourceKindLabel(kind: string): string {
  if (kind.length === 0) return '自动'
  const label = SOURCE_KIND_LABELS.get(kind)
  return label === undefined ? kind : label
}

export function ParsingExtractPanel(props: ParsingExtractPanelProps) {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <ParsingExtractForm key={JSON.stringify([props.documentId, sessionKey])} {...props} sessionKey={sessionKey} />
}

function ParsingExtractForm({
  documentId,
  activeElements,
  onSelectEvidence,
  className,
  sessionKey,
}: ParsingExtractPanelProps & { sessionKey: string }) {
  const formId = useId()
  const [isCollapsed, setIsCollapsed] = useState(true)
  const [mode, setMode] = useState<ExtractionMode>('schema')
  const defaults = useMemo(() => suggestDefaults(activeElements), [activeElements])
  const [drafts, setDrafts] = useState<Partial<Record<ExtractionMode, ExtractionDraft>>>({})
  const savedDraft = drafts[mode]
  const draft = savedDraft === undefined ? defaults : savedDraft
  const payload = useMemo(() => buildExtractionRequest(mode, draft), [draft, mode])
  const fingerprint = JSON.stringify(payload)
  const [result, setResult] = useState<ExtractionResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const requestRef = useRef<AbortController | null>(null)
  const hasDocument = documentId !== undefined && documentId !== null && documentId.length > 0
  const hasPreviousResult = result !== null && (isRunning || error !== null || result.fingerprint !== fingerprint)

  useLayoutEffect(
    () => () => {
      requestRef.current?.abort()
      requestRef.current = null
    },
    [],
  )

  const availableKinds = useMemo(() => {
    const values = new Set(['', 'seal', 'equation', 'table', 'image', 'heading', 'paragraph'])
    for (const element of activeElements) values.add(element.kind)
    if (draft.sourceKind.length > 0) values.add(draft.sourceKind)
    return Array.from(values)
  }, [activeElements, draft.sourceKind])

  const availableVisualKinds = useMemo(() => {
    const values = new Set([''])
    for (const element of activeElements) {
      const kind = getParsingElementVisualKind(element)
      if (kind !== null && kind.length > 0) values.add(kind)
    }
    if (draft.sourceVisualKind.length > 0) values.add(draft.sourceVisualKind)
    return Array.from(values)
  }, [activeElements, draft.sourceVisualKind])
  const showVisualKindField =
    (draft.sourceKind === '' || draft.sourceKind === 'image') && availableVisualKinds.length > 1

  function changeDraft(change: Partial<ExtractionDraft>) {
    setDrafts((current) => {
      const existing = current[mode]
      return { ...current, [mode]: { ...(existing === undefined ? defaults : existing), ...change } }
    })
    setError(null)
  }

  function changeSourceKind(sourceKind: string) {
    const sourceVisualKind = sourceKind === '' || sourceKind === 'image' ? draft.sourceVisualKind : ''
    changeDraft({ sourceKind, sourceVisualKind })
  }

  function changeMode(nextMode: ExtractionMode) {
    setMode(nextMode)
    setError(null)
  }

  async function runExtraction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (documentId === undefined || documentId === null || documentId.length === 0 || requestRef.current !== null)
      return
    if (getAuthSessionKey() !== sessionKey) return
    if (draft.fieldName.trim().length === 0) {
      setError('请输入字段名。')
      return
    }
    const request = new AbortController()
    requestRef.current = request
    const isCurrent = () => requestRef.current === request && getAuthSessionKey() === sessionKey
    setDrafts((current) => (current[mode] === undefined ? { ...current, [mode]: draft } : current))
    setIsRunning(true)
    setError(null)
    try {
      const response = await parsingApi.extract(documentId, payload, { signal: request.signal })
      if (isCurrent()) setResult({ response, fingerprint })
    } catch (error) {
      if (isCurrent()) setError(formatApiError(error, '抽取失败'))
    } finally {
      if (requestRef.current === request) {
        requestRef.current = null
        setIsRunning(false)
      }
    }
  }

  return (
    <div className={cn('border-b border-border/60 bg-muted/10 px-5 py-3', className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">结构化抽取</div>
          <p className="mt-1 text-[12px] leading-5 text-muted-foreground/80">
            使用服务器当前保存的解析结果抽取字段，并返回对应文字、页码和区域。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-expanded={!isCollapsed}
            aria-controls={`${formId}-content`}
            onClick={() => setIsCollapsed((current) => !current)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground transition-colors duration-150 hover:text-foreground/80"
          >
            {isCollapsed ? (
              <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {isCollapsed ? '展开' : '收起'}
          </button>
          <div
            role="group"
            aria-label="抽取方式"
            className="inline-flex items-center rounded-lg border border-border bg-card p-1"
          >
            <button
              type="button"
              aria-pressed={mode === 'schema'}
              disabled={isRunning}
              onClick={() => changeMode('schema')}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs transition-colors duration-150',
                mode === 'schema'
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground/80',
              )}
            >
              按字段
            </button>
            <button
              type="button"
              aria-pressed={mode === 'prompt'}
              disabled={isRunning}
              onClick={() => changeMode('prompt')}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs transition-colors duration-150',
                mode === 'prompt'
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground/80',
              )}
            >
              按提示词
            </button>
          </div>
        </div>
      </div>

      {!isCollapsed ? (
        <div id={`${formId}-content`} className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
          <form onSubmit={runExtraction} className="rounded-xl border border-border/60 bg-card p-3">
            <fieldset disabled={isRunning} className="min-w-0 space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor={`${formId}-field`} className="text-[11px] text-muted-foreground">
                    字段名
                  </Label>
                  <Input
                    id={`${formId}-field`}
                    name="fieldName"
                    required
                    value={draft.fieldName}
                    onChange={(event) => changeDraft({ fieldName: event.target.value })}
                    placeholder="company_name"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor={`${formId}-kind`} className="text-[11px] text-muted-foreground">
                    来源类型
                  </Label>
                  <select
                    id={`${formId}-kind`}
                    name="sourceKind"
                    value={draft.sourceKind}
                    onChange={(event) => changeSourceKind(event.target.value)}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm"
                  >
                    {availableKinds.map((kind) => (
                      <option key={kind} value={kind}>
                        {getSourceKindLabel(kind)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              {showVisualKindField ? (
                <div className="space-y-1.5">
                  <Label htmlFor={`${formId}-visual-kind`} className="text-[11px] text-muted-foreground">
                    图片子类
                  </Label>
                  <select
                    id={`${formId}-visual-kind`}
                    name="sourceVisualKind"
                    value={draft.sourceVisualKind}
                    onChange={(event) => changeDraft({ sourceVisualKind: event.target.value })}
                    className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm"
                  >
                    {availableVisualKinds.map((kind) => (
                      <option key={kind} value={kind}>
                        {kind.length === 0 ? '自动' : kind}
                      </option>
                    ))}
                  </select>
                </div>
              ) : null}
              <div className="space-y-1.5">
                <Label htmlFor={`${formId}-aliases`} className="text-[11px] text-muted-foreground">
                  别名
                </Label>
                <Input
                  id={`${formId}-aliases`}
                  name="aliases"
                  value={draft.aliases}
                  onChange={(event) => changeDraft({ aliases: event.target.value })}
                  placeholder="公司, 公章"
                />
              </div>
              {mode === 'prompt' ? (
                <div className="space-y-1.5">
                  <Label htmlFor={`${formId}-prompt`} className="text-[11px] text-muted-foreground">
                    提示词（可选）
                  </Label>
                  <Textarea
                    id={`${formId}-prompt`}
                    name="prompt"
                    value={draft.prompt}
                    onChange={(event) => changeDraft({ prompt: event.target.value })}
                    className="min-h-[96px]"
                    placeholder="提取主要公式"
                  />
                </div>
              ) : null}
            </fieldset>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-[11px] text-muted-foreground/80">
                {hasDocument ? '抽取基于已保存的结果。' : '请先解析并保存当前文件。'}
              </p>
              <LoadingButton type="submit" loading={isRunning} disabled={!hasDocument} className="gap-2">
                <WandSparkles className="h-4 w-4" aria-hidden="true" />
                运行抽取
              </LoadingButton>
            </div>
            {error !== null ? (
              <p role="alert" className="mt-3 text-sm text-destructive">
                {error}
              </p>
            ) : null}
          </form>

          <div className="rounded-xl border border-border/60 bg-card p-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">抽取结果</div>
              {hasPreviousResult ? <span className="text-[11px] text-muted-foreground">上次成功结果</span> : null}
            </div>
            {result === null ? (
              <p className="mt-3 text-sm text-muted-foreground">
                {isRunning ? '正在抽取字段…' : '运行抽取后显示字段值与证据。'}
              </p>
            ) : Object.keys(result.response.result).length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">未抽取到字段。</p>
            ) : (
              <div className="mt-2 space-y-2">
                {Object.entries(result.response.result).map(([fieldName, field]) => (
                  <div key={fieldName} className={styles.extractionField}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={styles.resultIcon} aria-hidden="true"><FileSearch className="size-3.5" /></span>
                      <span className="text-[11px] font-medium text-foreground">{fieldName}</span>
                      {field.strategy ? (
                        <span className="rounded-full border border-border/60 px-2 py-0.5 text-[11px] text-muted-foreground">
                          {field.strategy}
                        </span>
                      ) : null}
                      {typeof field.confidence === 'number' ? (
                        <span className={styles.countBadge}>
                          {field.confidence.toFixed(2)}
                        </span>
                      ) : null}
                    </div>
                    <div className="mt-1 text-sm font-medium text-foreground">
                      {field.value === undefined || field.value === null
                        ? '无结果'
                        : field.value.length === 0
                          ? '空文本'
                          : field.value}
                    </div>
                    {field.evidence.length > 0 ? (
                      <div className="mt-2 space-y-1">
                        {field.evidence.map((evidence, index) => (
                          <button
                            key={`${fieldName}:${evidence.element_id ?? index}`}
                            type="button"
                            onClick={() => onSelectEvidence({ fieldName, evidence })}
                            data-testid="extract-evidence-button"
                            className="w-full rounded-md border border-border/60 bg-card px-2 py-1 text-left text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/5"
                          >
                            <span className="flex flex-wrap items-center gap-2">
                              <span>{formatParsingPages(getParsingPages(evidence))}</span>
                              {evidence.kind ? <span>{evidence.kind}</span> : null}
                              {evidence.visual_kind ? <span>{evidence.visual_kind}</span> : null}
                              {evidence.element_id ? <span>{evidence.element_id}</span> : null}
                            </span>
                            {evidence.bbox ? (
                              <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground/85">
                                bbox {formatBbox(evidence.bbox)}
                              </span>
                            ) : null}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
