'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Bookmark, Download, Loader2, Save, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { cn, detachPromise } from '@/lib/utils'
import { chunkPresetApi } from '@/lib/api'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { downloadTextFile, sanitizeFilename } from '@/components/chunk-preview/utils/export'
import type { ChunkPreset } from '@/types'

function clampInt(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.trunc(value)))
}

function decodeSeparatorInput(raw: string) {
  const value = (raw || '').trim()
  if (!value) return ''
  try {
    return JSON.parse(`"${value.replaceAll("\"", '\\"')}"`)
  } catch {
    return value
  }
}

export function ChunkPresetPanel({ className }: Readonly<{ className?: string }>) {
  const pipelineCtx = usePipelineOptions()
  const importRef = useRef<HTMLInputElement>(null)

  const {
    datasetId,
    setDatasetId,
    parserBackend,
    setParserBackend,
    chunkStrategy,
    chunkSize,
    chunkOverlap,
    separatorPreset,
    separatorCustom,
    keepSeparator,
    separatorMaxChunkSize,
    updateSettings,
    updateSeparatorSettings,
  } = useChunkPreview()

  const [items, setItems] = useState<ChunkPreset[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedId, setSelectedId] = useState<string>('')

  const [saveAsOpen, setSaveAsOpen] = useState(false)
  const [saveAsName, setSaveAsName] = useState('')
  const [saveAsDescription, setSaveAsDescription] = useState('')
  const [saving, setSaving] = useState(false)

  const selectedPreset = useMemo(() => items.find((p) => p.id === selectedId) || null, [items, selectedId])

  const effectiveSeparator = useMemo(() => {
    const presetMap: Record<string, string> = {
      paragraph: '\n\n',
      line: '\n',
      sentence_cn: '。', // cn
      sentence_en: '.', // en
      markdown_hr: '---',
      markdown_h1: '# ',
      markdown_h2: '## ',
    }

    if (separatorPreset && separatorPreset !== 'custom') {
      return presetMap[separatorPreset] ?? '\n\n'
    }

    const raw = String(separatorCustom || '').trim()
    if (!raw) return '\n\n'
    return decodeSeparatorInput(raw) || '\n\n'
  }, [separatorCustom, separatorPreset])

  const buildPayload = () => {
    const payload: Record<string, any> = {
      dataset_id: datasetId || undefined,
      parser_backend: parserBackend,
      chunk_strategy: chunkStrategy,
      chunk_size: chunkSize,
      chunk_overlap: chunkOverlap,
      pipeline: pipelineCtx.enabled ? pipelineCtx.options : undefined,
    }

    if (chunkStrategy === 'separator') {
      payload.separator_preset = separatorPreset || 'paragraph'
      payload.keep_separator = Boolean(keepSeparator)
      payload.separator_max_chunk_size = Number(separatorMaxChunkSize) || 0
      if ((separatorPreset || '') === 'custom') {
        payload.separator = effectiveSeparator || '\n\n'
      }
    }

    return payload
  }

  const applyPayload = async (payload: any) => {
    const parsed = payload && typeof payload === 'object' ? payload : {}

    if (typeof parsed.dataset_id === 'string') setDatasetId(String(parsed.dataset_id))
    else if (parsed.dataset_id == null) setDatasetId('')

    if (typeof parsed.parser_backend === 'string') setParserBackend(String(parsed.parser_backend))

    const nextStrategy = typeof parsed.chunk_strategy === 'string' ? String(parsed.chunk_strategy) : undefined
    const nextSize = Number(parsed.chunk_size)
    const nextOverlap = Number(parsed.chunk_overlap)

    updateSettings({
      ...(nextStrategy ? { strategy: nextStrategy } : {}),
      ...(Number.isFinite(nextSize) ? { chunkSize: clampInt(nextSize, 50, 4000) } : {}),
      ...(Number.isFinite(nextOverlap) ? { chunkOverlap: clampInt(nextOverlap, 0, 1000) } : {}),
    })

    if (typeof parsed.separator_preset === 'string') {
      updateSeparatorSettings({ separatorPreset: String(parsed.separator_preset) })
    }
    if (typeof parsed.separator === 'string') {
      updateSeparatorSettings({ separatorCustom: String(parsed.separator) })
    }
    if (typeof parsed.keep_separator === 'boolean') {
      updateSeparatorSettings({ keepSeparator: Boolean(parsed.keep_separator) })
    }
    if (Number.isFinite(Number(parsed.separator_max_chunk_size))) {
      updateSeparatorSettings({
        separatorMaxChunkSize: clampInt(Number(parsed.separator_max_chunk_size), 0, 20000),
      })
    }

    const pipeline = parsed.pipeline
    if (pipeline && typeof pipeline === 'object') {
      pipelineCtx.setEnabled(true)
      for (const [k, v] of Object.entries(pipeline)) {
        if (k in pipelineCtx.options) {
          pipelineCtx.updateOption(k as any, v as any)
        }
      }
    }
  }

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const ds = (datasetId || '').trim()
      const res = await chunkPresetApi.list({
        limit: 200,
        ...(ds ? { dataset_id: ds, include_global: true } : {}),
      })
      const next = (res?.items || [])
      setItems(next)
      if (selectedId && !next.some((p) => p.id === selectedId)) {
        setSelectedId('')
      }
    } catch (err: any) {
      toast.error((err?.message as string) || '加载 presets 失败')
    } finally {
      setLoading(false)
    }
  }, [datasetId, selectedId])

  useEffect(() => {
    detachPromise(refresh())
  }, [refresh])

  const onSave = async () => {
    if (!selectedPreset) {
      setSaveAsOpen(true)
      return
    }
    setSaving(true)
    try {
      const payload = buildPayload()
      await chunkPresetApi.update(selectedPreset.id, {
        name: selectedPreset.name,
        description: selectedPreset.description ?? null,
        payload,
      })
      await refresh()
      toast.success('已更新 preset')
    } catch (err: any) {
      toast.error((err?.message as string) || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const onSaveAs = async () => {
    const name = (saveAsName || '').trim()
    if (!name) {
      toast.error('请输入 preset 名称')
      return
    }

    setSaving(true)
    try {
      const payload = buildPayload()
      const created = await chunkPresetApi.create({
        name,
        description: (saveAsDescription || '').trim() || null,
        payload,
      })
      await refresh()
      setSelectedId(created.id)
      setSaveAsOpen(false)
      toast.success('已创建 preset')
    } catch (err: any) {
      toast.error((err?.message as string) || '创建失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={cn('space-y-2 rounded-xl border border-border/60 bg-background p-3 shadow-sm', className)}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Bookmark className="w-4 h-4 text-primary" />
          <div className="text-xs font-semibold text-foreground">Chunk Presets</div>
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 px-2 text-[11px]"
          onClick={() => detachPromise(refresh())}
          disabled={loading || saving}
          aria-label="刷新 presets"
        >
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" /> : '刷新'}
        </Button>
      </div>

      <div className="space-y-2">
        <Select
          value={selectedId || '__none__'}
          onValueChange={(value) => {
            const nextId = value === '__none__' ? '' : value
            setSelectedId(nextId)
            const preset = items.find((p) => p.id === nextId)
            if (preset?.payload) {
              detachPromise(applyPayload(preset.payload))
              toast.success(`已应用 preset：${preset.name}`)
            }
          }}
        >
          <SelectTrigger className="h-9 bg-background">
            <SelectValue placeholder="选择 preset" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">（不使用 preset）</SelectItem>
            {items.map((p) => (
              <SelectItem key={p.id} value={p.id}>
                {p.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            className="h-8 px-3 text-[11px]"
            onClick={() => detachPromise(onSave())}
            disabled={saving}
          >
            {saving ? <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin motion-reduce:animate-none" /> : <Save className="w-3.5 h-3.5 mr-2" />}
            保存
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 px-3 text-[11px]"
            onClick={() => {
              setSaveAsName(selectedPreset?.name ? `${selectedPreset.name} Copy` : '')
              setSaveAsDescription(selectedPreset?.description || '')
              setSaveAsOpen(true)
            }}
            disabled={saving}
          >
            另存为
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 px-3 text-[11px]"
            disabled={saving}
            onClick={() => {
              const payload = buildPayload()
              const filename = `${sanitizeFilename(selectedPreset?.name || 'chunk-preset')}.json`
              downloadTextFile(filename, JSON.stringify(payload, null, 2), 'application/json;charset=utf-8')
              toast.success('已导出 JSON')
            }}
          >
            <Download className="w-3.5 h-3.5 mr-2" />
            导出
          </Button>
          <input
            ref={importRef}
            type="file"
            accept="application/json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              e.target.value = ''
              if (!file) return
              file
                .text()
                .then(async (text) => {
                  const data = JSON.parse(text || '{}')
                  await applyPayload(data)
                  toast.success('已导入 JSON 并应用')
                })
                .catch((err: any) => toast.error((err?.message as string) || '导入失败'))
            }}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 px-3 text-[11px]"
            disabled={saving}
            onClick={() => importRef.current?.click()}
          >
            <Upload className="w-3.5 h-3.5 mr-2" />
            导入
          </Button>
        </div>
      </div>

      <Dialog open={saveAsOpen} onOpenChange={setSaveAsOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>保存为 Chunk Preset</DialogTitle>
            <DialogDescription>保存当前预览参数，方便团队复用。</DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">名称</div>
              <Input value={saveAsName} onChange={(e) => setSaveAsName(e.target.value)} placeholder="例如：通用-长文档" />
            </div>
            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">描述（可选）</div>
              <Textarea
                value={saveAsDescription}
                onChange={(e) => setSaveAsDescription(e.target.value)}
                placeholder="适用场景、注意事项..."
                className="min-h-[80px]"
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setSaveAsOpen(false)} disabled={saving}>
              取消
            </Button>
            <Button type="button" onClick={() => detachPromise(onSaveAs())} disabled={saving}>
              {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin motion-reduce:animate-none" /> : null}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
