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
import { reportClientWarning } from '@/lib/client-logging'
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

const GOVERNANCE_SWITCHES: Array<{
  key: keyof DocumentPipelineOptions
  label: string
  description: string
  effect: string
  defaultChecked: boolean
}> = [
  {
    key: 'governance_enabled',
    label: '启用治理清洗',
    description: '打开后才会执行下面这些清洗步骤。',
    effect: '关闭时只保留原始解析结果，不做清洗。',
    defaultChecked: true,
  },
  {
    key: 'governance_unwrap_lines',
    label: '合并异常换行',
    description: '修复 PDF/网页复制导致的一句话被拆成多行。',
    effect: '检索片段更连贯，减少短碎句。',
    defaultChecked: true,
  },
  {
    key: 'governance_remove_common_lines',
    label: '去重复页眉页脚',
    description: '删除多页文档里反复出现的公司名、页码、版权行。',
    effect: '降低噪声分块和重复召回。',
    defaultChecked: true,
  },
  {
    key: 'governance_remove_toc_lines',
    label: '移除目录行',
    description: '识别“1.2 标题 ...... 12”这类目录/索引行。',
    effect: '避免目录页被当成正文入库。',
    defaultChecked: true,
  },
  {
    key: 'governance_remove_noise_lines',
    label: '清理低价值噪声',
    description: '过滤孤立符号、过短碎片、明显导航残留。',
    effect: '让 Markdown 更像可读正文。',
    defaultChecked: true,
  },
  {
    key: 'governance_remove_boilerplate',
    label: '去模板化废话',
    description: '删除网页横幅、cookie 提示、固定免责声明等样板文本。',
    effect: '适合网页导入、知识库导出和聊天记录。',
    defaultChecked: false,
  },
  {
    key: 'governance_normalize_tables',
    label: '整理 Markdown 表格',
    description: '规范表格空格、列宽和分隔符。',
    effect: '让表格更稳定地进入切块和检索。',
    defaultChecked: false,
  },
  {
    key: 'governance_normalize_urls',
    label: '规范链接',
    description: '统一 URL 表达，可配合去掉 utm 等跟踪参数。',
    effect: '减少同一链接的重复写入。',
    defaultChecked: false,
  },
]

const RULE_PACK_COPY: Record<string, { label: string; description: string }> = {
  chat_export_noise: {
    label: '聊天导出噪声',
    description: '清理会话导出里的时间戳、系统提示和重复分隔符。',
  },
  cn_finance_report_artifacts: {
    label: '金融报告噪声',
    description: '清理年报、公告、招股书中常见披露声明和证券标识行。',
  },
  cn_gov_redhead_artifacts: {
    label: '政府公文尾部',
    description: '清理红头公文中的抄送、签发、印发和主题词等低价值行。',
  },
  cn_medical_record_artifacts: {
    label: '医疗记录表头',
    description: '清理病案号、床号、医生、科室等医疗文档展示性字段。',
  },
  confluence_jira_noise: {
    label: 'Confluence / Jira 残留',
    description: '清理企业知识库导出的导航、面包屑和页面脚注。',
  },
  email_disclaimer: {
    label: '邮件免责声明',
    description: '删除邮件尾部的保密声明、转发脚注和冗余签名。',
  },
  feishu_lark_noise: {
    label: '飞书 / Lark 导出',
    description: '清理飞书知识库导出的元信息、协作者和导出标识。',
  },
  markdown_export_noise: {
    label: 'Markdown 导出噪声',
    description: '清理导出工具生成的锚点、空标题和重复标记。',
  },
  notion_export_noise: {
    label: 'Notion 导出噪声',
    description: '处理 Notion 导出中的创建时间、编辑时间和导出标识。',
  },
  pdf_header_footer_cn: {
    label: '中文 PDF 页眉页脚',
    description: '针对中文 PDF 的页码、页眉、页脚重复行。',
  },
  pdf_watermark: {
    label: 'PDF 水印',
    description: '删除扫描件或导出 PDF 中常见水印文本。',
  },
  web_cookie_banners: {
    label: '网页 Cookie 横幅',
    description: '过滤 cookie 同意、隐私提示等网页固定横幅。',
  },
  web_navigation: {
    label: '网页导航菜单',
    description: '清理网页导入里的导航栏、侧栏和页脚链接。',
  },
  wechat_mp_noise: {
    label: '微信公众号噪声',
    description: '清理公众号转载、来源、二维码和阅读提示类文本。',
  },
}

const INPUT_FORMAT_COPY: Record<'markdown' | 'html', { label: string; description: string }> = {
  markdown: {
    label: 'Markdown / 纯文本',
    description: '适合 PDF、Office、TXT 解析后的正文。',
  },
  html: {
    label: 'HTML / 网页',
    description: '适合网页、知识库导出和富文本源。',
  },
}

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
        reportClientWarning('Load governance rule packs failed', err)
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

  const updatePatchBoolean = (key: keyof DocumentPipelineOptions, value: boolean) => {
    applyPipelinePatchUpdate(
      key,
      value,
      setPipelinePatch,
      setPatchJsonError,
      setPatchJsonDirty
    )
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
  const enabledGovernanceSwitchCount = GOVERNANCE_SWITCHES.filter((item) =>
    Boolean(pipelinePatch?.[item.key] ?? item.defaultChecked)
  ).length
  const imageRemovalMode = String(pipelinePatch?.governance_remove_images ?? 'none')
  const maxBlankLines = Number(pipelinePatch?.governance_max_blank_lines ?? 1)

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
          'fixed right-0 top-0 left-auto bottom-0 h-dvh w-full max-w-3xl translate-x-0 translate-y-0 rounded-none',
          'grid grid-rows-[auto,1fr] gap-0 p-0'
        )}
      >
        <div className="border-b border-border bg-popover/80 backdrop-blur-md p-5">
          <DialogHeader className="space-y-2">
            <DialogTitle className="flex items-center gap-2">
              <Braces className="size-5 text-primary" />
              {(() => {
    if (isCreate) {
        return '新建治理模板';
    }
    else if (isReadOnly) {
            return '查看治理模板';
        }
        else {
            return '编辑治理模板';
        }
})()}
            </DialogTitle>
            <DialogDescription className="text-xs">
              {(() => {
    if (isCreate) {
        return '创建后可用于入库策略或手动选择应用。';
    }
    else if (loadedProfile?.is_system) {
            return '内置模板只读；如需调整请复制为自定义模板。';
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

        <div className="min-h-0 overflow-auto bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.22))] p-5">
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
                  <Panel padding="lg" className="rounded-2xl border-border/55 bg-card/92 shadow-sm">
                    <div className="mb-4 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                      <span className="rounded-full border border-primary/20 bg-primary/10 px-2 py-1 font-medium text-primary">
                        配置摘要
                      </span>
                      <span>启用 {enabledGovernanceSwitchCount} 项清洗</span>
                      <span>·</span>
                      <span>规则包 {selectedRulePacks.length} 个</span>
                      <span>·</span>
                      <span>自定义正则 {regexRules.length} 条</span>
                      <span>·</span>
                      <span>空行最多 {maxBlankLines} 行</span>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-1">
                        <Label htmlFor="gp-name">模板名称</Label>
                        <Input
                          id="gp-name"
                          value={name}
                          onChange={(e) => setName(e.target.value)}
                          disabled={isReadOnly}
                        />
                      </div>
                      <div className="space-y-1">
                        <Label htmlFor="gp-key">唯一标识（可选）</Label>
                        <Input
                          id="gp-key"
                          value={key}
                          onChange={(e) => setKey(e.target.value)}
                          disabled={!isCreate || isReadOnly}
                          placeholder={isCreate ? 'e.g. team:pdf_text' : undefined}
                        />
                        {isCreate ? null : (
                          <div className="text-[11px] text-muted-foreground">
                            创建后不可修改；入库策略可用 id 或 key 引用该 Profile。
                          </div>
                        )}
                      </div>
                      <div className="md:col-span-2 space-y-1">
                        <Label htmlFor="gp-desc">用途说明</Label>
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

                  <Panel padding="lg" className="rounded-2xl border-border/55 bg-card/92 shadow-sm">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="font-semibold text-foreground">适用文件类型</div>
                        <div className="text-[12px] text-muted-foreground mt-1">
                          只是声明这个治理方案适合什么输入；后端不会强制拦截，但入库策略会用它做分流提示。
                        </div>
                      </div>
                      <div className="grid w-full grid-cols-1 gap-2 sm:w-[360px] sm:grid-cols-2">
                        {PROFILE_INPUT_FORMAT_VALUES.map((fmt) => {
                          const selected = inputFormats.includes(fmt)
                          const copy = INPUT_FORMAT_COPY[fmt]
                          return (
                            <label
                              key={fmt}
                              className={cn(
                                'flex cursor-pointer items-start gap-2 rounded-2xl border px-3 py-2 transition-colors',
                                selected
                                  ? 'border-primary/25 bg-primary/10 text-foreground'
                                  : 'border-border/55 bg-background/75 text-muted-foreground hover:border-primary/20 hover:bg-primary/5',
                                isReadOnly && 'cursor-default'
                              )}
                            >
                              <Checkbox
                                className="mt-0.5"
                                checked={selected}
                                onCheckedChange={() => toggleInputFormat(fmt)}
                                disabled={isReadOnly}
                              />
                              <span className="min-w-0">
                                <span className="block text-[12px] font-semibold">{copy.label}</span>
                                <span className="block text-[10.5px] leading-4 text-muted-foreground">{copy.description}</span>
                              </span>
                            </label>
                          )
                        })}
                      </div>
                    </div>
                  </Panel>

                  <Panel padding="lg" className="rounded-2xl border-border/55 bg-card/92 shadow-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-foreground">常用治理能力</div>
                        <div className="text-[12px] text-muted-foreground mt-1">
                          这里展示“要解决什么问题”和“会产生什么效果”。底层仍写入真实 pipeline_patch 字段。
                        </div>
                      </div>
                      <span className="rounded-full border border-border/55 bg-background/75 px-2 py-1 text-[11px] text-muted-foreground">
                        已启用 {enabledGovernanceSwitchCount} / {GOVERNANCE_SWITCHES.length}
                      </span>
                    </div>
                    <div data-profile-governance-switch-grid className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
                      {GOVERNANCE_SWITCHES.map((item) => {
                        const checked = Boolean(pipelinePatch?.[item.key] ?? item.defaultChecked)
                        return (
                          <label
                            key={String(item.key)}
                            className={cn(
                              'group flex cursor-pointer gap-3 rounded-2xl border p-3 transition-colors',
                              checked
                                ? 'border-primary/25 bg-primary/10'
                                : 'border-border/50 bg-background/70 hover:border-primary/20 hover:bg-primary/5',
                              isReadOnly && 'cursor-default'
                            )}
                          >
                            <Checkbox
                              className="mt-0.5"
                              checked={checked}
                              onCheckedChange={(v) => updatePatchBoolean(item.key, Boolean(v))}
                              disabled={isReadOnly}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="flex items-center justify-between gap-2">
                                <span className="text-[13px] font-semibold text-foreground">{item.label}</span>
                                <span className="rounded-full border border-border/50 bg-background/65 px-1.5 py-0.5 font-mono text-[9.5px] text-muted-foreground">
                                  {checked ? 'ON' : 'OFF'}
                                </span>
                              </span>
                              <span className="mt-1 block text-[11.5px] leading-5 text-muted-foreground">
                                {item.description}
                              </span>
                              <span className="mt-2 block rounded-xl border border-border/35 bg-background/55 px-2 py-1 text-[11px] leading-4 text-muted-foreground">
                                效果：{item.effect}
                              </span>
                              <code className="mt-1.5 block truncate text-[10px] text-muted-foreground/55">
                                写入字段：{String(item.key)}
                              </code>
                            </span>
                          </label>
                        )
                      })}
                    </div>

                    <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
                      <div className="rounded-2xl border border-border/50 bg-background/75 p-3">
                        <Label className="text-[13px] font-semibold text-foreground">图片处理</Label>
                        <div className="mt-1 text-[11.5px] leading-5 text-muted-foreground">
                          只在确实影响检索时删除图片占位；默认建议保留。
                        </div>
                        <Select
                          value={imageRemovalMode}
                          onValueChange={(v) => updatePatchValue('governance_remove_images', v)}
                          disabled={isReadOnly}
                        >
                          <SelectTrigger className="mt-3 h-9 rounded-xl border-border/60 bg-card">
                            <SelectValue placeholder="保留图片" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="none">保留图片标记</SelectItem>
                            <SelectItem value="decorative">只移除装饰图片</SelectItem>
                            <SelectItem value="all">移除全部图片标记</SelectItem>
                          </SelectContent>
                        </Select>
                        <div className="mt-2 text-[10.5px] text-muted-foreground/70">
                          当前写入：governance_remove_images = {imageRemovalMode}
                        </div>
                      </div>
                      <div className="rounded-2xl border border-border/50 bg-background/75 p-3">
                        <Label className="text-[13px] font-semibold text-foreground">最大连续空行</Label>
                        <div className="mt-1 text-[11.5px] leading-5 text-muted-foreground">
                          控制清洗后 Markdown 的留白密度，通常 1 行最适合入库。
                        </div>
                        <Input
                          type="number"
                          min={0}
                          className="mt-3 h-9 rounded-xl border-border/60 bg-card"
                          value={String(maxBlankLines)}
                          onChange={(e) => updatePatchValue('governance_max_blank_lines', Number(e.target.value || 1))}
                          disabled={isReadOnly}
                        />
                        <div className="mt-2 text-[10.5px] text-muted-foreground/70">
                          当前写入：governance_max_blank_lines
                        </div>
                      </div>
                    </div>
                  </Panel>

                  <Panel padding="lg" className="rounded-2xl border-border/55 bg-card/92 shadow-sm">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="font-semibold text-foreground">场景规则包</div>
                        <div className="text-[12px] text-muted-foreground mt-1">
                          服务端内置的场景化清洗规则。优先选来源场景，不建议一口气全选。
                        </div>
                      </div>
                      {loadingRulePacks ? (
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                          加载中...
                        </div>
                      ) : (
                        <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-1 text-[11px] text-muted-foreground">
                          已选 {selectedRulePacks.length} 个
                        </span>
                      )}
                    </div>

                    {availableRulePacks.length ? (
                      <div data-profile-rule-pack-grid className="mt-4 grid grid-cols-1 gap-2 md:grid-cols-2">
                        {availableRulePacks.map((pack) => {
                          const selected = selectedRulePacks.includes(pack)
                          const copy = RULE_PACK_COPY[pack] || {
                            label: pack.replaceAll('_', ' '),
                            description: '服务端返回的自定义规则包。',
                          }
                          return (
                            <label
                              key={pack}
                              className={cn(
                                'flex cursor-pointer items-start gap-2 rounded-2xl border px-3 py-2 transition-colors',
                                selected
                                  ? 'border-primary/25 bg-primary/10'
                                  : 'border-border/50 bg-background/70 hover:border-primary/20 hover:bg-primary/5',
                                isReadOnly && 'cursor-default'
                              )}
                            >
                              <Checkbox
                                className="mt-0.5"
                                checked={selected}
                                onCheckedChange={() => toggleRulePack(pack)}
                                disabled={isReadOnly}
                              />
                              <span className="min-w-0">
                                <span className="block text-[12.5px] font-semibold text-foreground">{copy.label}</span>
                                <span className="mt-0.5 block text-[11px] leading-4 text-muted-foreground">{copy.description}</span>
                                <code className="mt-1 block truncate text-[10px] text-muted-foreground/55">{pack}</code>
                              </span>
                            </label>
                          )
                        })}
                      </div>
                    ) : (
                      <div className="mt-3 text-sm text-muted-foreground">
                        {loadingRulePacks ? '正在加载规则包...' : '暂无可用规则包'}
                      </div>
                    )}
                  </Panel>

                  <details
                    data-profile-advanced-json
                    className="group rounded-2xl border border-border/55 bg-card/82 shadow-sm"
                    open={Boolean(patchJsonError || patchJsonDirty)}
                  >
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
                      <span>
                        <span className="flex items-center gap-2 font-semibold text-foreground">
                          <Braces className="size-4 text-muted-foreground" />
                          高级 JSON
                        </span>
                        <span className="mt-1 block text-[12px] text-muted-foreground">
                          只有需要手动覆盖后端字段时再展开；上方开关会自动同步到这里。
                        </span>
                      </span>
                      <span className="rounded-full border border-border/55 bg-background/75 px-2 py-1 text-[11px] text-muted-foreground">
                        pipeline_patch
                      </span>
                    </summary>
                    <div className="border-t border-border/45 px-4 pb-4 pt-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-[12px] text-muted-foreground">
                          修改 JSON 后点击“应用 JSON”解析；解析失败不会覆盖当前配置。
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
                      <Textarea
                        value={patchJson}
                        onChange={(e) => {
                          setPatchJson(e.target.value)
                          setPatchJsonError(null)
                          setPatchJsonDirty(true)
                        }}
                        disabled={isReadOnly}
                        className={cn('mt-3 min-h-[180px] font-mono text-[12px]', patchJsonError && 'aria-[invalid=true]')}
                        aria-invalid={patchJsonError ? 'true' : 'false'}
                      />
                      {patchJsonError ? (
                        <div className="mt-2 text-[12px] text-destructive">JSON 解析失败：{patchJsonError}</div>
                      ) : null}
                    </div>
                  </details>

                  <details
                    data-profile-regex-rules
                    className="group rounded-2xl border border-border/55 bg-card/82 shadow-sm"
                    open={regexRules.length > 0}
                  >
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
                      <span>
                        <span className="font-semibold text-foreground">自定义正则规则</span>
                        <span className="mt-1 block text-[12px] text-muted-foreground">
                          只有内置规则包不够时再加；服务端会做 ReDoS 风险校验与长度限制。
                        </span>
                      </span>
                      <span className="rounded-full border border-border/55 bg-background/75 px-2 py-1 text-[11px] text-muted-foreground">
                        {regexRules.length} 条
                      </span>
                    </summary>

                    <div className="border-t border-border/45 px-4 pb-4 pt-3">
                      <div className="flex justify-end">
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
                                <Label className="text-[12px] text-muted-foreground">匹配表达式 pattern</Label>
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
                                <Label className="text-[12px] text-muted-foreground">匹配选项 flags</Label>
                                <Input
                                  type="number"
                                  value={String(r.flags ?? 0)}
                                  onChange={(e) => updateRule(idx, { flags: Number(e.target.value || 0) })}
                                  disabled={isReadOnly}
                                />
                              </div>
                              <div className="md:col-span-3 space-y-1">
                                <Label className="text-[12px] text-muted-foreground">替换内容 repl</Label>
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
                        <div className="mt-3 rounded-xl border border-dashed border-border/60 bg-background/60 px-3 py-4 text-sm text-muted-foreground">
                          暂无自定义规则。通常先使用上方场景规则包，只有遇到固定噪声样式时再新增正则。
                        </div>
                      )}
                    </div>
                  </details>
                </div>
              </TabsContent>

              <TabsContent value="test" className="mt-0">
                <div className="space-y-4">
                  <Panel padding="lg" className="rounded-2xl border-border/55 bg-card/92 shadow-sm">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-1">
                        <Label>测试输入类型</Label>
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
                        <Label>HTML 正文 XPath（可选）</Label>
                        <Input
                          value={testHtmlXPath}
                          onChange={(e) => setTestHtmlXPath(e.target.value)}
                          disabled={testInputFormat !== 'html'}
                          placeholder="//article | //main"
                        />
                      </div>
                      <div className="md:col-span-2 space-y-1">
                        <Label>粘贴一段样例内容</Label>
                        <Textarea value={testInput} onChange={(e) => setTestInput(e.target.value)} className="min-h-[180px] font-mono text-[12px]" />
                        <div className="text-[11px] text-muted-foreground">
                          用真实样例跑一次，可以看到清洗后的 Markdown、命中规则和 diff，不需要靠猜。
                        </div>
                      </div>
                    </div>
                  </Panel>

                  {testResp ? (
                    <div className="grid grid-cols-1 gap-4">
                      <Panel padding="lg" className="rounded-2xl border-border/55 bg-card/92 shadow-sm">
                        <div className="flex items-center gap-2">
                          <FileText className="size-4 text-muted-foreground" />
                          <div className="font-semibold text-foreground">清洗结果（Markdown）</div>
                        </div>
                        <Textarea
                          value={String(testResp.markdown || '')}
                          readOnly
                          className="mt-3 min-h-[220px] font-mono text-[12px] bg-muted/20"
                        />
                      </Panel>

                      <CleanPreviewRuleStatsPanel ruleStats={testResp.rule_stats} />

                      {testResp.diff_unified ? (
                        <Panel padding="lg" className="rounded-2xl border-border/55 bg-card/92 shadow-sm">
                          <div className="flex items-center gap-2">
                            <Braces className="size-4 text-muted-foreground" />
                            <div className="font-semibold text-foreground">改动对比（Diff）</div>
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
                    <Panel padding="lg" className="rounded-2xl border-dashed border-border/60 bg-card/70">
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
