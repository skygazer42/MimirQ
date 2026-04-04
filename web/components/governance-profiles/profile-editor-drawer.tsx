'use client'

import { type Dispatch, type SetStateAction, useCallback, useEffect, useMemo, useState } from 'react'
import { Braces, FileText, Loader2, Play, Save } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { governanceApi, pipelineApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { coerceOneOf } from '@/lib/one-of'
import { cn, detachPromise } from '@/lib/utils'
import type {
  CleanPreviewResponse,
  DocumentPipelineOptions,
  GovernanceProfileCreate,
  GovernanceProfileOut,
  GovernanceProfilePayload,
  RegexRuleModel,
} from '@/types'
import { buildCleanPreviewRequestFromGovernanceProfile } from '@/lib/governance-profile-utils'
import { CleanPreviewRuleStatsPanel } from '@/components/governance-profiles/clean-preview-rule-stats-panel'

type Mode = 'create' | 'edit' | 'view'

type Props = {
  open: boolean
  mode: Mode
  profileRef?: string | null
  seedCreate?: GovernanceProfileCreate | null
  onOpenChange: (open: boolean) => void
  onSaved?: (profile: GovernanceProfileOut) => void
  onCreated?: (profile: GovernanceProfileOut) => void
}

const PROFILE_EDITOR_TABS = ['edit', 'test'] as const
const PROFILE_INPUT_FORMAT_VALUES = ['markdown', 'html'] as const

function defaultPayload(): GovernanceProfilePayload {
  return {
    version: '1',
    input_formats: ['markdown'],
    pipeline_patch: {
      governance_enabled: true,
      governance_remove_toc_lines: true,
      governance_remove_noise_lines: true,
      governance_unwrap_lines: true,
      governance_remove_common_lines: true,
      governance_max_blank_lines: 1,
    },
    regex_rules: [],
  }
}

function applyPipelinePatchUpdate(
  key: keyof DocumentPipelineOptions,
  value: DocumentPipelineOptions[keyof DocumentPipelineOptions],
  setPipelinePatch: Dispatch<SetStateAction<DocumentPipelineOptions>>,
  setPatchJsonError: Dispatch<SetStateAction<string | null>>,
  setPatchJsonDirty: Dispatch<SetStateAction<boolean>>,
) {
  setPipelinePatch((prev) => ({ ...prev, [key]: value }))
  setPatchJsonError(null)
  setPatchJsonDirty(false)
}

function safeParseJson<T>(text: string): { ok: true; value: T } | { ok: false; error: string } {
  try {
    const obj = JSON.parse(text)
    return { ok: true, value: obj as T }
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Invalid JSON' }
  }
}

function pythonReFlagsToJs(flags: number): string {
  // Best-effort mapping (Python re flags int -> JS flags).
  // Python: IGNORECASE=2, MULTILINE=8, DOTALL=16
  let out = ''
  const n = Number(flags || 0)
  if (n & 2) out += 'i'
  if (n & 8) out += 'm'
  if (n & 16) out += 's'
  return out
}

function stripLeadingInlineFlags(pattern: string): { pattern: string; inlineJsFlags: string } {
  const raw = String(pattern || '')
  const match = /^\(\?([A-Za-z]+)\)/.exec(raw)
  if (!match) return { pattern: raw, inlineJsFlags: '' }
  const flags = match[1] || ''
  let js = ''
  for (const ch of flags) {
    if (ch === 'i' && !js.includes('i')) js += 'i'
    if (ch === 'm' && !js.includes('m')) js += 'm'
    if (ch === 's' && !js.includes('s')) js += 's'
  }
  return { pattern: raw.slice(match[0].length), inlineJsFlags: js }
}

function validateRegexRuleBestEffort(pattern: string, flags: number): string | null {
  const raw = String(pattern || '').trim()
  if (!raw) return 'pattern required'

  // Try to make common Python patterns "compile-checkable" in JS.
  const stripped = stripLeadingInlineFlags(raw)
  const jsFlags = Array.from(new Set((pythonReFlagsToJs(flags) + stripped.inlineJsFlags).split(''))).join('')
  const jsPattern = stripped.pattern
    .replaceAll(String.raw`\A`, '^')
    .replaceAll(String.raw`\Z`, '$')

  try {
    new RegExp(jsPattern, jsFlags)
    return null
  } catch (err) {
    return err instanceof Error ? err.message : 'Invalid regex'
  }
}

export function ProfileEditorDrawer({
  open,
  mode,
  profileRef,
  seedCreate,
  onOpenChange,
  onSaved,
  onCreated,
}: Readonly<Props>) {
  const isReadOnly = mode === 'view'
  const isCreate = mode === 'create'

  const [activeTab, setActiveTab] = useState<'edit' | 'test'>('edit')
  const [loadingProfile, setLoadingProfile] = useState(false)
  const [saving, setSaving] = useState(false)

  const [loadedProfile, setLoadedProfile] = useState<GovernanceProfileOut | null>(null)
  const [name, setName] = useState('')
  const [key, setKey] = useState('')
  const [description, setDescription] = useState('')
  const [inputFormats, setInputFormats] = useState<Array<'markdown' | 'html'>>(['markdown'])
  const [pipelinePatch, setPipelinePatch] = useState<DocumentPipelineOptions>({})
  const [regexRules, setRegexRules] = useState<RegexRuleModel[]>([])
  const [availableRulePacks, setAvailableRulePacks] = useState<string[]>([])
  const [loadingRulePacks, setLoadingRulePacks] = useState(false)

  const [patchJson, setPatchJson] = useState('')
  const [patchJsonError, setPatchJsonError] = useState<string | null>(null)
  const [patchJsonDirty, setPatchJsonDirty] = useState(false)

  // Sandbox test state.
  const [testInputFormat, setTestInputFormat] = useState<'markdown' | 'html'>('markdown')
  const [testHtmlXPath, setTestHtmlXPath] = useState('')
  const [testInput, setTestInput] = useState<string>('# Sample\n\nfoo')
  const [testRunning, setTestRunning] = useState(false)
  const [testResp, setTestResp] = useState<CleanPreviewResponse | null>(null)

  const payload: GovernanceProfilePayload = useMemo(
    () => ({
      version: '1',
      input_formats: inputFormats.length ? inputFormats : ['markdown'],
      pipeline_patch: pipelinePatch,
      regex_rules: regexRules,
    }),
    [inputFormats, pipelinePatch, regexRules]
  )

  const selectedRulePacks = useMemo(
    () => (Array.isArray(pipelinePatch?.governance_rule_packs) ? pipelinePatch.governance_rule_packs : []),
    [pipelinePatch]
  )

  const resetDraft = useCallback(() => {
    setLoadedProfile(null)
    setName('')
    setKey('')
    setDescription('')
    setInputFormats(['markdown'])
    setPipelinePatch(defaultPayload().pipeline_patch)
    setRegexRules([])
    setPatchJson(JSON.stringify(defaultPayload().pipeline_patch, null, 2))
    setPatchJsonError(null)
    setPatchJsonDirty(false)
    setActiveTab('edit')
    setTestResp(null)
    setTestInput('# Sample\n\nfoo')
    setTestInputFormat('markdown')
    setTestHtmlXPath('')
  }, [])

  // Load profile when opening (edit/view).
  useEffect(() => {
    if (!open) return

    if (isCreate) {
      const seeded = seedCreate
      const p = seeded?.payload || defaultPayload()
      setLoadedProfile(null)
      setName(seeded ? String(seeded.name || '') : '')
      setKey(seeded && typeof seeded.key === 'string' ? String(seeded.key || '') : '')
      setDescription(seeded ? String(seeded.description || '') : '')
      setInputFormats(p.input_formats)
      setPipelinePatch(p.pipeline_patch)
      setRegexRules(p.regex_rules)
      setPatchJson(JSON.stringify(p.pipeline_patch, null, 2))
      setPatchJsonError(null)
      setPatchJsonDirty(false)
      setActiveTab('edit')
      setTestResp(null)
      return
    }

    const ref = (profileRef || '').trim()
    if (!ref) return

    let cancelled = false
    setLoadingProfile(true)
    detachPromise((async () => {
      try {
        const prof = await pipelineApi.getGovernanceProfile(ref)
        if (cancelled) return
        setLoadedProfile(prof)
        setName(String(prof.name || ''))
        setKey(String(prof.key || ''))
        setDescription(String(prof.description || ''))
        setInputFormats(prof.payload?.input_formats || ['markdown'])
        setPipelinePatch(prof.payload?.pipeline_patch ?? {})
        setRegexRules(prof.payload?.regex_rules ?? [])
        setPatchJson(JSON.stringify(prof.payload?.pipeline_patch ?? {}, null, 2))
        setPatchJsonError(null)
        setPatchJsonDirty(false)
        setActiveTab('edit')
        setTestResp(null)
      } catch (err: unknown) {
        toast.error(formatApiError(err, '加载 Profile 失败'))
      } finally {
        if (!cancelled) setLoadingProfile(false)
      }
    })())

    return () => {
      cancelled = true
    }
  }, [open, isCreate, profileRef, seedCreate])

  // Load available rule packs for multi-select UI (best-effort).
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoadingRulePacks(true)
    detachPromise((async () => {
      try {
        const resp = await governanceApi.listRulePacks()
        if (cancelled) return
        setAvailableRulePacks(Array.isArray(resp.items) ? resp.items : [])
      } catch (err) {
        console.warn('Load governance rule packs failed:', err)
        if (!cancelled) setAvailableRulePacks([])
      } finally {
        if (!cancelled) setLoadingRulePacks(false)
      }
    })())
    return () => {
      cancelled = true
    }
  }, [open])

  // Keep JSON view synced for quick-toggle edits.
  useEffect(() => {
    if (!open) return
    // If user has a JSON error, do not overwrite their edits.
    if (patchJsonError) return
    if (patchJsonDirty) return
    setPatchJson(JSON.stringify(pipelinePatch, null, 2))
  }, [pipelinePatch, open, patchJsonError, patchJsonDirty])

  const toggleInputFormat = (fmt: 'markdown' | 'html') => {
    setInputFormats((prev) => {
      const set = new Set(prev)
      if (set.has(fmt)) set.delete(fmt)
      else set.add(fmt)
      const next = Array.from(set)
      return next.length ? next : ['markdown']
    })
  }

  const updatePatchValue = <K extends keyof DocumentPipelineOptions>(
    key: K,
    value: DocumentPipelineOptions[K],
  ) => {
    applyPipelinePatchUpdate(key, value, setPipelinePatch, setPatchJsonError, setPatchJsonDirty)
  }

  const toggleRulePack = (pack: string) => {
    const key = pack.trim()
    if (!key) return
    setPipelinePatch((prev) => {
      const current = Array.isArray(prev?.governance_rule_packs) ? prev.governance_rule_packs : []
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return {
        ...prev,
        governance_rule_packs: Array.from(next).sort((a, b) => a.localeCompare(b)),
      }
    })
    setPatchJsonError(null)
    setPatchJsonDirty(false)
  }

  const applyPatchJson = () => {
    const parsed = safeParseJson<DocumentPipelineOptions>(patchJson)
    if (!parsed.ok) {
      setPatchJsonError(parsed.error)
      return
    }
    setPatchJsonError(null)
    setPatchJsonDirty(false)
    setPipelinePatch(parsed.value)
  }

  const addRule = () => {
    setRegexRules((prev) => [...(prev || []), { pattern: '', repl: '', flags: 0 }])
  }

  const updateRule = (idx: number, patch: Partial<RegexRuleModel>) => {
    setRegexRules((prev) => {
      const next = [...(prev || [])]
      const cur = next[idx] || {}
      next[idx] = { ...cur, ...patch }
      return next
    })
  }

  const removeRule = (idx: number) => {
    setRegexRules((prev) => (prev || []).filter((_, i) => i !== idx))
  }

  const canSave = !isReadOnly && !saving && !loadingProfile

  const save = async () => {
    if (!canSave) return
    const trimmedName = name.trim()
    if (!trimmedName) {
      toast.error('name 不能为空')
      return
    }

    setSaving(true)
    try {
      if (isCreate) {
        const payloadCreate: GovernanceProfileCreate = {
          name: trimmedName,
          description: description.trim() || undefined,
          payload,
        }
        const k = key.trim()
        if (k) payloadCreate.key = k
        const created = await pipelineApi.createGovernanceProfile(payloadCreate)
        toast.success('已创建 Profile')
        onCreated?.(created)
        onOpenChange(false)
      } else {
        const ref = (profileRef || '').trim()
        if (!ref) {
          toast.error('profile_ref 缺失')
          return
        }
        const updated = await pipelineApi.updateGovernanceProfile(ref, {
          name: trimmedName,
          description: description.trim() || '',
          payload,
        })
        toast.success('已保存 Profile')
        onSaved?.(updated)
        onOpenChange(false)
      }
    } catch (err: unknown) {
      toast.error(formatApiError(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const runTest = async () => {
    setTestRunning(true)
    setTestResp(null)
    try {
      const req = buildCleanPreviewRequestFromGovernanceProfile(payload, testInput, {
        inputFormat: testInputFormat,
        htmlXPath: testHtmlXPath.trim() || undefined,
        includeDiff: true,
        diffMaxLines: 2000,
      })
      const resp = await pipelineApi.cleanPreview(req)
      setTestResp(resp)
      toast.success('清洗预览完成')
    } catch (err: unknown) {
      setTestResp(null)
      toast.error(formatApiError(err, '清洗预览失败'))
    } finally {
      setTestRunning(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next)
        if (!next) resetDraft()
      }}
    >
      <DialogContent
        className={cn(
          // Drawer layout: right-aligned, full height.
          'fixed right-0 top-0 left-auto bottom-0 h-dvh w-full max-w-xl translate-x-0 translate-y-0 rounded-none',
          'grid grid-rows-[auto,1fr] gap-0 p-0'
        )}
      >
        <div className="border-b border-border bg-popover/80 backdrop-blur-md p-5">
          <DialogHeader className="space-y-2">
            <DialogTitle className="flex items-center gap-2">
              <Braces className="size-5 text-primary" />
              {(() => {
    if (isCreate) {
        return '新建治理 Profile';
    }
    else if (isReadOnly) {
            return '查看治理 Profile';
        }
        else {
            return '编辑治理 Profile';
        }
})()}
            </DialogTitle>
            <DialogDescription className="text-xs">
              {(() => {
    if (isCreate) {
        return '创建后可用于入库策略（ingestion policy）或手动选择应用。';
    }
    else if (loadedProfile?.is_system) {
            return '内置 Profile 只读；如需调整请复制为自定义 Profile。';
        }
        else {
            return '修改后仅影响后续入库/重跑（不会自动回写历史版本）。';
        }
})()}
            </DialogDescription>
          </DialogHeader>

          <div className="mt-4 flex items-center justify-between gap-3">
            <Tabs
              value={activeTab}
              onValueChange={(value) => setActiveTab(coerceOneOf(PROFILE_EDITOR_TABS, value, 'edit'))}
            >
              <TabsList className="rounded-xl">
                <TabsTrigger value="edit" className="rounded-lg px-3">
                  编辑
                </TabsTrigger>
                <TabsTrigger value="test" className="rounded-lg px-3">
                  沙盒测试
                </TabsTrigger>
              </TabsList>
            </Tabs>

            <div className="flex items-center gap-2">
              {activeTab === 'test' ? (
                <Button
                  type="button"
                  size="sm"
                  className="rounded-xl gap-2"
                  onClick={() => detachPromise(runTest())}
                  disabled={testRunning}
                >
                  {testRunning ? (
                    <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                  ) : (
                    <Play className="size-4" />
                  )}
                  运行
                </Button>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  className="rounded-xl gap-2"
                  onClick={() => detachPromise(save())}
                  disabled={!canSave}
                >
                  {saving ? (
                    <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                  ) : (
                    <Save className="size-4" />
                  )}
                  保存
                </Button>
              )}
            </div>
          </div>
        </div>

        <div className="min-h-0 overflow-auto p-5">
          {loadingProfile ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground gap-2">
              <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
              加载中…
            </div>
          ) : (
            <Tabs
              value={activeTab}
              onValueChange={(value) => setActiveTab(coerceOneOf(PROFILE_EDITOR_TABS, value, 'edit'))}
            >
              <TabsContent value="edit" className="mt-0">
                <div className="space-y-4">
                  <Panel padding="lg" className="rounded-2xl">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-1">
                        <Label htmlFor="gp-name">Name</Label>
                        <Input
                          id="gp-name"
                          value={name}
                          onChange={(e) => setName(e.target.value)}
                          disabled={isReadOnly}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="gp-key">Key (optional)</Label>
                        <Input
                          id="gp-key"
                          value={key}
                          onChange={(e) => setKey(e.target.value)}
                          disabled={!isCreate || isReadOnly}
                          placeholder={isCreate ? 'e.g. team:pdf_text' : undefined}
                        />
                        {isCreate ? null : (
                          <div className="text-[11px] text-muted-foreground">
                            key 创建后不可修改（可用 id 作为 profile_ref）
                          </div>
                        )}
                      </div>
                      <div className="md:col-span-2 space-y-1">
                        <Label htmlFor="gp-desc">Description</Label>
                        <Textarea
                          id="gp-desc"
                          value={description}
                          onChange={(e) => setDescription(e.target.value)}
                          disabled={isReadOnly}
                          className="min-h-[84px]"
                        />
                      </div>
                    </div>
                  </Panel>

                  <Panel padding="lg" className="rounded-2xl">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-semibold text-foreground">Input formats</div>
                        <div className="text-[12px] text-muted-foreground mt-1">
                          声明该 Profile 适用的输入类型（用于入库策略分流/提示，不强制）。
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="flex items-center gap-2 text-sm">
                          <Checkbox
                            checked={inputFormats.includes('markdown')}
                            onCheckedChange={() => toggleInputFormat('markdown')}
                            disabled={isReadOnly}
                          />
                          markdown
                        </div>
                        <div className="flex items-center gap-2 text-sm">
                          <Checkbox
                            checked={inputFormats.includes('html')}
                            onCheckedChange={() => toggleInputFormat('html')}
                            disabled={isReadOnly}
                          />
                          html
                        </div>
                      </div>
                    </div>
                  </Panel>

                  <Panel padding="lg" className="rounded-2xl">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-foreground">常用治理开关</div>
                        <div className="text-[12px] text-muted-foreground mt-1">
                          这些字段会写入 payload.pipeline_patch（可在下方 Advanced JSON 中查看/覆盖）。
                        </div>
                      </div>
                    </div>
                    <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={Boolean(pipelinePatch?.governance_enabled ?? true)}
                          onCheckedChange={(v) => updatePatchValue('governance_enabled', Boolean(v))}
                          disabled={isReadOnly}
                        />
                        governance_enabled
                      </div>
                      <div className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={Boolean(pipelinePatch?.governance_unwrap_lines ?? true)}
                          onCheckedChange={(v) => updatePatchValue('governance_unwrap_lines', Boolean(v))}
                          disabled={isReadOnly}
                        />
                        unwrap_lines
                      </div>
                      <div className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={Boolean(pipelinePatch?.governance_remove_common_lines ?? true)}
                          onCheckedChange={(v) => updatePatchValue('governance_remove_common_lines', Boolean(v))}
                          disabled={isReadOnly}
                        />
                        remove_common_lines
                      </div>
                      <div className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={Boolean(pipelinePatch?.governance_remove_toc_lines ?? true)}
                          onCheckedChange={(v) => updatePatchValue('governance_remove_toc_lines', Boolean(v))}
                          disabled={isReadOnly}
                        />
                        remove_toc_lines
                      </div>
                      <div className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={Boolean(pipelinePatch?.governance_remove_noise_lines ?? true)}
                          onCheckedChange={(v) => updatePatchValue('governance_remove_noise_lines', Boolean(v))}
                          disabled={isReadOnly}
                        />
                        remove_noise_lines
                      </div>
                      <div className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={Boolean(pipelinePatch?.governance_remove_boilerplate ?? false)}
                          onCheckedChange={(v) => updatePatchValue('governance_remove_boilerplate', Boolean(v))}
                          disabled={isReadOnly}
                        />
                        remove_boilerplate
                      </div>
                      <div className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={Boolean(pipelinePatch?.governance_normalize_tables ?? false)}
                          onCheckedChange={(v) => updatePatchValue('governance_normalize_tables', Boolean(v))}
                          disabled={isReadOnly}
                        />
                        normalize_tables
                      </div>
                      <div className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={Boolean(pipelinePatch?.governance_normalize_urls ?? false)}
                          onCheckedChange={(v) => updatePatchValue('governance_normalize_urls', Boolean(v))}
                          disabled={isReadOnly}
                        />
                        normalize_urls
                      </div>
                      <div className="flex items-center gap-3">
                        <Label className="text-sm text-muted-foreground">remove_images</Label>
                        <div className="flex-1">
                          <Select
                            value={String(pipelinePatch?.governance_remove_images ?? 'none')}
                            onValueChange={(v) => updatePatchValue('governance_remove_images', v)}
                            disabled={isReadOnly}
                          >
                            <SelectTrigger className="h-9 rounded-xl">
                              <SelectValue placeholder="none" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none">none</SelectItem>
                              <SelectItem value="decorative">decorative</SelectItem>
                              <SelectItem value="all">all</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <Label className="text-sm text-muted-foreground">max_blank_lines</Label>
                        <Input
                          type="number"
                          className="h-9 rounded-xl"
                          value={String(pipelinePatch?.governance_max_blank_lines ?? 1)}
                          onChange={(e) => updatePatchValue('governance_max_blank_lines', Number(e.target.value || 1))}
                          disabled={isReadOnly}
                        />
                      </div>
                    </div>
                  </Panel>

                  <Panel padding="lg" className="rounded-2xl">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-foreground">Rule packs</div>
                        <div className="text-[12px] text-muted-foreground mt-1">
                          Optional server-defined presets (expanded into regex rules). Use these for common sources like PDFs / web imports.
                        </div>
                      </div>
                      {loadingRulePacks ? (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                          Loading...
                        </div>
                      ) : (
                        <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-1 text-[11px] text-muted-foreground">
                          {selectedRulePacks.length} selected
                        </span>
                      )}
                    </div>

                    {availableRulePacks.length ? (
                      <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-2">
                        {availableRulePacks.map((pack) => (
                          <label key={pack} className="flex items-center gap-2 text-sm">
                            <Checkbox
                              checked={selectedRulePacks.includes(pack)}
                              onCheckedChange={() => toggleRulePack(pack)}
                              disabled={isReadOnly}
                            />
                            <span className="font-mono text-xs">{pack}</span>
                          </label>
                        ))}
                      </div>
                    ) : (
                      <div className="mt-3 text-sm text-muted-foreground">
                        {loadingRulePacks ? 'Loading rule packs...' : 'No rule packs available'}
                      </div>
                    )}
                  </Panel>

                  <Panel padding="lg" className="rounded-2xl">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-foreground flex items-center gap-2">
                          <Braces className="size-4 text-muted-foreground" />
                          Advanced JSON (pipeline_patch)
                        </div>
                        <div className="text-[12px] text-muted-foreground mt-1">
                          直接编辑 payload.pipeline_patch JSON；点击“应用 JSON”进行解析。
                        </div>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="rounded-xl"
                        onClick={applyPatchJson}
                        disabled={isReadOnly}
                      >
                        应用 JSON
                      </Button>
                    </div>
                    <div className="mt-3">
                      <Textarea
                        value={patchJson}
                        onChange={(e) => {
                          setPatchJson(e.target.value)
                          setPatchJsonError(null)
                          setPatchJsonDirty(true)
                        }}
                        disabled={isReadOnly}
                        className={cn('font-mono text-[12px] min-h-[220px]', patchJsonError && 'aria-[invalid=true]')}
                        aria-invalid={patchJsonError ? 'true' : 'false'}
                      />
                      {patchJsonError ? (
                        <div className="mt-2 text-[12px] text-destructive">JSON 解析失败：{patchJsonError}</div>
                      ) : null}
                    </div>
                  </Panel>

                  <Panel padding="lg" className="rounded-2xl">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-semibold text-foreground">Regex rules</div>
                        <div className="text-[12px] text-muted-foreground mt-1">
                          规则会在清洗阶段作为额外规则执行；服务端会做 ReDoS 风险校验与长度限制。
                        </div>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="rounded-xl"
                        onClick={addRule}
                        disabled={isReadOnly}
                      >
                        新增规则
                      </Button>
                    </div>

                    {regexRules.length ? (
                      <div className="mt-4 space-y-3">
                        {regexRules.map((r, idx) => (
                          <div key={[r.pattern || '', r.repl || '', String(r.flags ?? 0)].join('::')} className="rounded-xl border border-border bg-muted/30 p-3">
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                              <div className="md:col-span-2 space-y-1">
                                <Label className="text-[12px] text-muted-foreground">pattern</Label>
                                <Input
                                  value={r.pattern || ''}
                                  onChange={(e) => updateRule(idx, { pattern: e.target.value })}
                                  disabled={isReadOnly}
                                  placeholder="(?mi)^..."
                                />
                                {(() => {
                                  const err = validateRegexRuleBestEffort(r.pattern || '', Number(r.flags ?? 0))
                                  return err ? <div className="text-[11px] text-destructive">{err}</div> : null
                                })()}
                              </div>
                              <div className="space-y-1">
                                <Label className="text-[12px] text-muted-foreground">flags</Label>
                                <Input
                                  type="number"
                                  value={String(r.flags ?? 0)}
                                  onChange={(e) => updateRule(idx, { flags: Number(e.target.value || 0) })}
                                  disabled={isReadOnly}
                                />
                              </div>
                              <div className="md:col-span-3 space-y-1">
                                <Label className="text-[12px] text-muted-foreground">repl</Label>
                                <Input
                                  value={r.repl || ''}
                                  onChange={(e) => updateRule(idx, { repl: e.target.value })}
                                  disabled={isReadOnly}
                                  placeholder=""
                                />
                              </div>
                            </div>
                            <div className="mt-3 flex justify-end">
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                className="rounded-xl"
                                onClick={() => removeRule(idx)}
                                disabled={isReadOnly}
                              >
                                删除
                              </Button>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="mt-3 text-sm text-muted-foreground">暂无规则</div>
                    )}
                  </Panel>
                </div>
              </TabsContent>

              <TabsContent value="test" className="mt-0">
                <div className="space-y-4">
                  <Panel padding="lg" className="rounded-2xl">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-1">
                        <Label>input_format</Label>
                        <Select
                          value={testInputFormat}
                          onValueChange={(value) => setTestInputFormat(coerceOneOf(PROFILE_INPUT_FORMAT_VALUES, value, 'markdown'))}
                        >
                          <SelectTrigger className="h-10 rounded-xl">
                            <SelectValue placeholder="markdown" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="markdown">markdown</SelectItem>
                            <SelectItem value="html">html</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1">
                        <Label>html_xpath (optional)</Label>
                        <Input
                          value={testHtmlXPath}
                          onChange={(e) => setTestHtmlXPath(e.target.value)}
                          disabled={testInputFormat !== 'html'}
                          placeholder="//article | //main"
                        />
                      </div>
                      <div className="md:col-span-2 space-y-1">
                        <Label>input</Label>
                        <Textarea value={testInput} onChange={(e) => setTestInput(e.target.value)} className="min-h-[180px] font-mono text-[12px]" />
                      </div>
                    </div>
                  </Panel>

                  {testResp ? (
                    <div className="grid grid-cols-1 gap-4">
                      <Panel padding="lg" className="rounded-2xl">
                        <div className="flex items-center gap-2">
                          <FileText className="size-4 text-muted-foreground" />
                          <div className="font-semibold text-foreground">输出（markdown）</div>
                        </div>
                        <Textarea
                          value={String(testResp.markdown || '')}
                          readOnly
                          className="mt-3 min-h-[220px] font-mono text-[12px] bg-muted/20"
                        />
                      </Panel>

                      <CleanPreviewRuleStatsPanel ruleStats={testResp.rule_stats} />

                      {testResp.diff_unified ? (
                        <Panel padding="lg" className="rounded-2xl">
                          <div className="flex items-center gap-2">
                            <Braces className="size-4 text-muted-foreground" />
                            <div className="font-semibold text-foreground">Diff（unified）</div>
                          </div>
                          <Textarea
                            value={String(testResp.diff_unified || '')}
                            readOnly
                            className="mt-3 min-h-[220px] font-mono text-[12px] bg-muted/20"
                          />
                          {testResp.diff_truncated ? (
                            <div className="mt-2 text-[12px] text-muted-foreground">diff 已截断</div>
                          ) : null}
                        </Panel>
                      ) : null}
                    </div>
                  ) : (
                    <Panel padding="lg" className="rounded-2xl border-dashed">
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Play className="size-4" />
                        点击“运行”调用 clean-preview 查看清洗效果与 diff
                      </div>
                    </Panel>
                  )}
                </div>
              </TabsContent>
            </Tabs>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
