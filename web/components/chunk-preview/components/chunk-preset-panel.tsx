'use client'

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Copy, Loader2, RefreshCw, Save } from '@/components/icons'
import { toast } from 'sonner'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

import { cn, detachPromise } from '@/lib/utils'
import styles from './workbench/config-dialog.module.css'
import { chunkPresetApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { useChunkPreviewConfig } from '@/components/chunk-preview/use-chunk-preview-config'
import type { ChunkPreset } from '@/types/processing'

export function ChunkPresetPanel({ className }: Readonly<{ className?: string }>) {
  const t = useTranslations('ChunkPreview')
  const commonT = useTranslations('Common')
  const { datasetId } = useChunkPreview()
  const { buildConfig, applyConfig } = useChunkPreviewConfig('preset')

  const [presetList, setPresetList] = useState<{ datasetId: string; items: ChunkPreset[] } | null>(null)
  const [loading, setLoading] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const [saveAsOpen, setSaveAsOpen] = useState(false)
  const [saveAsName, setSaveAsName] = useState('')
  const [saveAsDescription, setSaveAsDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const mountedRef = useRef(false)
  const scopeRevisionRef = useRef(0)
  const listRequestRef = useRef(0)
  const saveRef = useRef<{ sessionRevision: number } | null>(null)
  const draftRevisionRef = useRef(0)

  useLayoutEffect(() => {
    mountedRef.current = true
    setSaving(false)
    return () => {
      mountedRef.current = false
      scopeRevisionRef.current += 1
      listRequestRef.current += 1
      saveRef.current = null
    }
  }, [datasetId])

  const items = presetList?.datasetId === datasetId ? presetList.items : []
  const selectedPreset = items.find((preset) => preset.id === selectedId)

  const refresh = useCallback(async () => {
    const request = ++listRequestRef.current
    const scope = getAuthCacheScope()
    const sessionRevision = getAuthSessionRevision()
    const isCurrent = () =>
      mountedRef.current &&
      listRequestRef.current === request &&
      getAuthCacheScope() === scope &&
      getAuthSessionRevision() === sessionRevision
    setLoading(true)
    try {
      const scopeDatasetId = datasetId.trim()
      const res = await chunkPresetApi.list({
        limit: 200,
        ...(scopeDatasetId.length > 0 ? { dataset_id: scopeDatasetId, include_global: true } : {}),
      })
      if (!isCurrent()) return
      setPresetList({ datasetId, items: res.items })
      setSelectedId((previous) => (res.items.some((preset) => preset.id === previous) ? previous : null))
    } catch (error: unknown) {
      if (isCurrent()) toast.error(formatApiError(error, t('chunkPresetPanel.loadFailed')))
    } finally {
      if (mountedRef.current && listRequestRef.current === request) setLoading(false)
    }
  }, [datasetId, t])

  useEffect(() => {
    detachPromise(refresh())
  }, [refresh])

  function acceptSavedPreset(preset: ChunkPreset) {
    listRequestRef.current += 1
    setLoading(false)
    setPresetList((current) => {
      const remaining = current?.datasetId === datasetId ? current.items.filter((item) => item.id !== preset.id) : []
      return { datasetId, items: [preset, ...remaining] }
    })
  }

  const onSave = async () => {
    const sessionRevision = getAuthSessionRevision()
    if (saveRef.current?.sessionRevision === sessionRevision) return
    if (!selectedPreset) {
      draftRevisionRef.current += 1
      setSaveAsName('')
      setSaveAsDescription('')
      setSaveAsOpen(true)
      return
    }
    const save = { sessionRevision }
    saveRef.current = save
    const scopeRevision = scopeRevisionRef.current
    const authScope = getAuthCacheScope()
    const isCurrent = () =>
      mountedRef.current &&
      scopeRevisionRef.current === scopeRevision &&
      getAuthCacheScope() === authScope &&
      getAuthSessionRevision() === sessionRevision
    setSaving(true)
    try {
      const payload = buildConfig()
      const updated = await chunkPresetApi.update(selectedPreset.id, {
        name: selectedPreset.name,
        description: selectedPreset.description ?? null,
        payload,
      })
      if (!isCurrent()) return
      acceptSavedPreset(updated)
      toast.success(t('chunkPresetPanel.updated'))
    } catch (error: unknown) {
      if (isCurrent()) toast.error(formatApiError(error, t('chunkPresetPanel.saveFailed')))
    } finally {
      if (saveRef.current === save) {
        saveRef.current = null
        if (mountedRef.current) setSaving(false)
      }
    }
  }

  const onSaveAs = async () => {
    const sessionRevision = getAuthSessionRevision()
    if (saveRef.current?.sessionRevision === sessionRevision) return
    const name = saveAsName.trim()
    if (name.length === 0) {
      toast.error(t('chunkPresetPanel.nameRequired'))
      return
    }

    const save = { sessionRevision }
    saveRef.current = save
    const scopeRevision = scopeRevisionRef.current
    const draftRevision = draftRevisionRef.current
    const authScope = getAuthCacheScope()
    const isCurrent = () =>
      mountedRef.current &&
      scopeRevisionRef.current === scopeRevision &&
      getAuthCacheScope() === authScope &&
      getAuthSessionRevision() === sessionRevision
    setSaving(true)
    try {
      const payload = buildConfig()
      const description = saveAsDescription.trim()
      const created = await chunkPresetApi.create({
        name,
        description: description.length === 0 ? null : description,
        payload,
      })
      if (!isCurrent()) return
      acceptSavedPreset(created)
      if (draftRevisionRef.current !== draftRevision) return
      setSelectedId(created.id)
      setSaveAsOpen(false)
      toast.success(t('chunkPresetPanel.createdAndSelected'))
    } catch (error: unknown) {
      if (isCurrent() && draftRevisionRef.current === draftRevision)
        toast.error(formatApiError(error, t('chunkPresetPanel.createFailed')))
    } finally {
      if (saveRef.current === save) {
        saveRef.current = null
        if (mountedRef.current) setSaving(false)
      }
    }
  }

  return (
    <section className={cn(styles.presetBar, className)} aria-label="切块预设">
      <span className={styles.presetLabel}>参数预设</span>
      <Select
        value={selectedPreset?.id ?? '__none__'}
        onValueChange={(value) => {
          draftRevisionRef.current += 1
          if (value === '__none__') {
            setSelectedId(null)
            return
          }
          const preset = items.find((item) => item.id === value)
          if (preset === undefined) return

          const result = applyConfig(preset.payload)
          if (!result.ok) {
            toast.error(result.error)
            return
          }
          setSelectedId(preset.id)
          toast.success(t('chunkPresetPanel.applied', { name: preset.name }))
        }}
      >
        <SelectTrigger aria-label="选择切块预设" className={styles.presetSelect}>
          <SelectValue placeholder={t('chunkPresetPanel.select')} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__none__">{t('chunkPresetPanel.none')}</SelectItem>
          {items.map((preset) => (
            <SelectItem key={preset.id} value={preset.id}>
              {preset.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button
        type="button"
        variant="ghost"
        className={styles.savePresetButton}
        aria-label={selectedPreset ? t('chunkPresetPanel.updatePreset') : t('chunkPresetPanel.savePreset')}
        title={selectedPreset ? t('chunkPresetPanel.updatePreset') : t('chunkPresetPanel.savePreset')}
        onClick={() => detachPromise(onSave())}
        disabled={saving}
      >
        {saving ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Save />}
        <span>{selectedPreset ? t('chunkPresetPanel.updatePreset') : t('chunkPresetPanel.savePreset')}</span>
      </Button>
      {selectedPreset && (
        <Button
          type="button"
          variant="ghost"
          className={styles.savePresetButton}
          aria-label={t('chunkPresetPanel.saveAs')}
          title={t('chunkPresetPanel.saveAs')}
          disabled={saving}
          onClick={() => {
            draftRevisionRef.current += 1
            setSaveAsName(`${selectedPreset.name} ${t('chunkPresetPanel.copySuffix')}`)
            setSaveAsDescription(selectedPreset.description ?? '')
            setSaveAsOpen(true)
          }}
        >
          <Copy />
          <span>{t('chunkPresetPanel.saveAs')}</span>
        </Button>
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className={styles.refreshPresets}
        onClick={() => detachPromise(refresh())}
        disabled={loading || saving}
        aria-label={t('chunkPresetPanel.refreshAria')}
      >
        {loading ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <RefreshCw />}
      </Button>
      {saveAsOpen && (
        <fieldset className={styles.presetForm} disabled={saving} aria-label="保存切块预设">
          <label>
            {t('chunkPresetPanel.name')}
            <Input
              autoFocus
              aria-label="预设名称"
              value={saveAsName}
              onChange={(event) => {
                draftRevisionRef.current += 1
                setSaveAsName(event.target.value)
              }}
              placeholder={t('chunkPresetPanel.namePlaceholder')}
            />
          </label>
          <label>
            {t('chunkPresetPanel.description')}
            <Textarea
              aria-label="预设说明"
              value={saveAsDescription}
              onChange={(event) => {
                draftRevisionRef.current += 1
                setSaveAsDescription(event.target.value)
              }}
              placeholder={t('chunkPresetPanel.descriptionPlaceholder')}
            />
          </label>
          <div>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                draftRevisionRef.current += 1
                setSaveAsOpen(false)
              }}
            >
              {commonT('cancel')}
            </Button>
            <Button type="button" disabled={saving} onClick={() => detachPromise(onSaveAs())}>
              {saving && <Loader2 className="animate-spin motion-reduce:animate-none" />}
              {commonT('save')}
            </Button>
          </div>
        </fieldset>
      )}
    </section>
  )
}
