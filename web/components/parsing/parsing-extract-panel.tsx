'use client'

import { useEffect, useMemo, useState } from 'react'
import { Loader2, WandSparkles } from 'lucide-react'

import { parsingApi } from '@/lib/api'
import type { ParsingElement, ParsingExtractEvidence, ParsingExtractRequest, ParsingExtractResponse } from '@/lib/api/parsing'
import { formatApiError } from '@/lib/api-errors'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'

type ParsingExtractPanelProps = {
  documentId?: string | null
  activeElements: ParsingElement[]
  onSelectEvidence?: (payload: { fieldName: string; evidence: ParsingExtractEvidence }) => void
  className?: string
}

function suggestDefaults(elements: ParsingElement[]) {
  const imageVisualKinds = new Set(
    elements
      .filter((item) => item.kind === 'image')
      .map((item) => String((item.attributes as Record<string, unknown> | null)?.visual_kind || '').trim())
      .filter(Boolean)
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
  const hasChartImage = elements.some(
    (item) => item.kind === 'image' && String((item.attributes as Record<string, unknown> | null)?.visual_kind || '').trim() === 'chart'
  )
  if (hasChartImage) {
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
      String(value || '')
        .split(/[,\n，]+/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  )
}

function formatBbox(bbox: ParsingElement['bbox']): string {
  if (!bbox) return ''
  return `${bbox.x0},${bbox.y0},${bbox.x1},${bbox.y1}`
}

function formatEvidencePages(evidence: ParsingExtractEvidence): string {
  const pages = Array.isArray(evidence.pages)
    ? evidence.pages.filter((value) => Number.isInteger(value) && value > 0)
    : []
  if (pages.length >= 2) {
    if (pages.length === 2 && pages[1] === pages[0] + 1) {
      return `跨页 ${pages[0]}-${pages[1]}`
    }
    return `跨页 ${pages.join(',')}`
  }
  if (typeof evidence.page === 'number') {
    return `页 ${evidence.page}`
  }
  return ''
}

export function ParsingExtractPanel({
  documentId,
  activeElements,
  onSelectEvidence,
  className,
}: Readonly<ParsingExtractPanelProps>) {
  const [mode, setMode] = useState<'schema' | 'prompt'>('schema')
  const [schemaFieldName, setSchemaFieldName] = useState('')
  const [schemaSourceKind, setSchemaSourceKind] = useState('')
  const [schemaSourceVisualKind, setSchemaSourceVisualKind] = useState('')
  const [schemaAliases, setSchemaAliases] = useState('')
  const [promptFieldName, setPromptFieldName] = useState('')
  const [promptSourceKind, setPromptSourceKind] = useState('')
  const [promptSourceVisualKind, setPromptSourceVisualKind] = useState('')
  const [promptAliases, setPromptAliases] = useState('')
  const [promptText, setPromptText] = useState('')
  const [result, setResult] = useState<ParsingExtractResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)

  const availableKinds = useMemo(() => {
    const values = new Set<string>(['', 'seal', 'equation', 'table', 'image', 'heading', 'paragraph'])
    for (const element of activeElements || []) {
      const kind = String(element.kind || '').trim()
      if (kind) values.add(kind)
    }
    return Array.from(values)
  }, [activeElements])
  const availableVisualKinds = useMemo(() => {
    const values = new Set<string>([''])
    for (const element of activeElements || []) {
      const visualKind = String((element.attributes as Record<string, unknown> | null)?.visual_kind || '').trim()
      if (visualKind) values.add(visualKind)
    }
    return Array.from(values)
  }, [activeElements])

  useEffect(() => {
    const defaults = suggestDefaults(activeElements)
    setSchemaFieldName(defaults.fieldName)
    setSchemaSourceKind(defaults.sourceKind)
    setSchemaSourceVisualKind(defaults.sourceVisualKind)
    setSchemaAliases(defaults.aliases)
    setPromptFieldName(defaults.fieldName)
    setPromptSourceKind(defaults.sourceKind)
    setPromptSourceVisualKind(defaults.sourceVisualKind)
    setPromptAliases(defaults.aliases)
    setPromptText(defaults.prompt)
    setResult(null)
    setError(null)
    setMode('schema')
  }, [activeElements, documentId])

  const handleRun = async () => {
    if (!documentId || isRunning) return
    setIsRunning(true)
    setError(null)

    try {
      let payload: ParsingExtractRequest
      if (mode === 'schema') {
        const fieldName = schemaFieldName.trim() || 'field'
        payload = {
          mode: 'schema',
          schema: {
            [fieldName]: {
              type: 'string',
              source_kind: schemaSourceKind.trim() || null,
              source_visual_kind: schemaSourceVisualKind.trim() || null,
              aliases: parseAliases(schemaAliases),
            },
          },
          max_evidence: 3,
        }
      } else {
        const fieldName = promptFieldName.trim() || 'prompt_result'
        payload = {
          mode: 'prompt',
          prompt: promptText.trim(),
          field_hints: {
            [fieldName]: {
              type: 'string',
              source_kind: promptSourceKind.trim() || null,
              source_visual_kind: promptSourceVisualKind.trim() || null,
              aliases: parseAliases(promptAliases),
            },
          },
          max_evidence: 3,
        }
      }

      const response = await parsingApi.extract(documentId, payload)
      setResult(response)
    } catch (err) {
      setError(formatApiError(err, '抽取失败'))
      setResult(null)
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className={cn('border-b border-border/60 bg-muted/10 px-5 py-3', className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            结构化抽取
          </div>
          <div className="mt-1 text-[12px] leading-5 text-muted-foreground/80">
            基于当前解析结果快速抽取字段，并返回页码与 bbox 证据。
          </div>
        </div>
        <div className="inline-flex items-center rounded-lg border border-border bg-background/90 p-1">
          <button
            type="button"
            onClick={() => setMode('schema')}
            className={cn(
              'rounded-md px-3 py-1.5 text-xs transition-colors duration-150',
              mode === 'schema' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground/80'
            )}
          >
            Schema
          </button>
          <button
            type="button"
            onClick={() => setMode('prompt')}
            className={cn(
              'rounded-md px-3 py-1.5 text-xs transition-colors duration-150',
              mode === 'prompt' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground/80'
            )}
          >
            Prompt
          </button>
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
        <div className="rounded-xl border border-border/60 bg-background/88 p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <div className="text-[11px] font-medium text-muted-foreground">字段名</div>
              <Input
                value={mode === 'schema' ? schemaFieldName : promptFieldName}
                onChange={(event) =>
                  mode === 'schema' ? setSchemaFieldName(event.target.value) : setPromptFieldName(event.target.value)
                }
                placeholder="company_name"
              />
            </div>
            <div className="space-y-1.5">
              <div className="text-[11px] font-medium text-muted-foreground">来源 kind</div>
              <select
                value={mode === 'schema' ? schemaSourceKind : promptSourceKind}
                onChange={(event) =>
                  mode === 'schema' ? setSchemaSourceKind(event.target.value) : setPromptSourceKind(event.target.value)
                }
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm"
              >
                {availableKinds.map((kind) => (
                  <option key={kind || 'auto'} value={kind}>
                    {kind || '自动'}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt-3 space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">来源 visual kind</div>
            <select
              value={mode === 'schema' ? schemaSourceVisualKind : promptSourceVisualKind}
              onChange={(event) =>
                mode === 'schema'
                  ? setSchemaSourceVisualKind(event.target.value)
                  : setPromptSourceVisualKind(event.target.value)
              }
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground shadow-sm"
            >
              {availableVisualKinds.map((visualKind) => (
                <option key={visualKind || 'auto'} value={visualKind}>
                  {visualKind || '自动'}
                </option>
              ))}
            </select>
          </div>

          <div className="mt-3 space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">别名</div>
            <Input
              value={mode === 'schema' ? schemaAliases : promptAliases}
              onChange={(event) =>
                mode === 'schema' ? setSchemaAliases(event.target.value) : setPromptAliases(event.target.value)
              }
              placeholder="公司, 公章"
            />
          </div>

          {mode === 'prompt' ? (
            <div className="mt-3 space-y-1.5">
              <div className="text-[11px] font-medium text-muted-foreground">提示词</div>
              <Textarea
                value={promptText}
                onChange={(event) => setPromptText(event.target.value)}
                className="min-h-[96px]"
                placeholder="提取主要公式"
              />
            </div>
          ) : null}

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[11px] text-muted-foreground/80">
              {documentId ? `doc: ${documentId}` : '当前文件尚未持久化，无法抽取'}
            </div>
            <Button
              type="button"
              disabled={!documentId || isRunning}
              onClick={() => void handleRun()}
              className="gap-2"
            >
              {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <WandSparkles className="h-4 w-4" />}
              运行抽取
            </Button>
          </div>
          {error ? <div className="mt-2 text-xs text-destructive">{error}</div> : null}
        </div>

        <div className="rounded-xl border border-border/60 bg-background/92 p-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            抽取结果
          </div>
          {result ? (
            <div className="mt-2 space-y-2">
              {Object.entries(result.result || {}).map(([fieldName, field]) => (
                <div key={fieldName} className="rounded-lg border border-border/60 bg-muted/10 p-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[11px] font-semibold text-foreground">{fieldName}</span>
                    <span className="rounded-full border border-border/60 px-2 py-0.5 text-[10px] text-muted-foreground">
                      {field.strategy || 'unknown'}
                    </span>
                    {typeof field.confidence === 'number' ? (
                      <span className="font-mono text-[10px] text-muted-foreground">{field.confidence.toFixed(2)}</span>
                    ) : null}
                  </div>
                  <div className="mt-1 text-sm font-medium text-foreground">{field.value || '无结果'}</div>
                  {(field.evidence || []).length > 0 ? (
                    <div className="mt-2 space-y-1">
                      {(field.evidence || []).map((evidence, index) => (
                        <button
                          key={`${fieldName}:${String(evidence.element_id || index)}`}
                          type="button"
                          onClick={() => onSelectEvidence?.({ fieldName, evidence })}
                          data-testid="extract-evidence-button"
                          className="w-full rounded-md border border-border/50 bg-background/80 px-2 py-1 text-left text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:bg-primary/5"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            {formatEvidencePages(evidence) ? <span>{formatEvidencePages(evidence)}</span> : null}
                            {evidence.kind ? <span>{evidence.kind}</span> : null}
                            {evidence.visual_kind ? <span>{evidence.visual_kind}</span> : null}
                            {evidence.element_id ? <span>{evidence.element_id}</span> : null}
                          </div>
                          {evidence.bbox ? (
                            <div className="mt-0.5 font-mono text-[10px] text-muted-foreground/85">
                              bbox {formatBbox(evidence.bbox)}
                            </div>
                          ) : null}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-3 text-sm text-muted-foreground/80">运行抽取后，这里会显示 value、confidence 和 evidence。</div>
          )}
        </div>
      </div>
    </div>
  )
}
