'use client'

import { useState } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Checkbox } from '@/components/ui/checkbox'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { PARSER_BACKEND_REGISTRY_OPTIONS } from '@/lib/parser-options'
import { formatApiError } from '@/lib/api-errors'
import { INGESTION_POLICY_TEMPLATES, PREPROCESS_STEP_CATALOG } from './policy-catalog'
import { draftToRule, type TemplatePlacement } from './policy-model'
import type { IngestionPolicyController } from './use-ingestion-policy'
import styles from './policy.module.css'

const NONE = '__inherit__'
export function PolicyRuleEditor({ c }: { c: IngestionPolicyController }) {
  const editor = c.editor!
  const [draft, setDraft] = useState(editor.draft), [tab, setTab] = useState('basic'), [error, setError] = useState('')
  const change = <K extends keyof typeof draft>(field: K, value: typeof draft[K]) => { setDraft(previous => ({ ...previous, [field]: value })); setError('') }
  const profiles = (c.profilesQuery.data?.items ?? []).map(profile => ({ value: profile.key || profile.id, label: profile.name })).filter((profile): profile is { value: string; label: string } => Boolean(profile.value))
  function apply(event: React.FormEvent) {
    event.preventDefault()
    try { c.applyRule(draftToRule(draft, c.rules, editor.originalId), editor.originalId) }
    catch (cause) {
      setError(cause instanceof SyntaxError ? '参数覆盖的 JSON 格式有误，请检查括号和引号。' : formatApiError(cause, '无法应用规则'))
      setTab(cause instanceof SyntaxError || (cause instanceof Error && cause.message.includes('JSON')) ? 'advanced' : 'basic')
    }
  }
  return <Dialog open onOpenChange={open => { if (!open) c.setEditor(null) }}><DialogContent className={styles.editorDialog} onCloseAutoFocus={event => { event.preventDefault(); c.restoreFocus() }}>
    <DialogHeader className={styles.dialogHeader}><DialogTitle>{editor.originalId ? '编辑规则' : '新增规则'}</DialogTitle><DialogDescription>{c.datasetQuery.data?.name} · 应用后需保存策略，配置才会生效。</DialogDescription></DialogHeader>
    <form className={styles.dialogForm} onSubmit={apply}>
      <Tabs value={tab} onValueChange={setTab} className={styles.editorTabs}><TabsList className={styles.tabsList} aria-label="规则配置"><TabsTrigger value="basic">匹配与处理</TabsTrigger><TabsTrigger value="preprocess">解析前预处理</TabsTrigger><TabsTrigger value="advanced">参数覆盖</TabsTrigger></TabsList>
        <div className={styles.dialogBody}>
          <TabsContent value="basic" forceMount hidden={tab !== 'basic'} className={styles.tabPanel}>
            <div className={styles.formGrid}>
              <div className={styles.field}><Label htmlFor="policy-rule-name">规则名称</Label><Input id="policy-rule-name" value={draft.name} maxLength={200} placeholder="例如：PDF 文本文档" onChange={event => change('name', event.target.value)} autoFocus /></div>
              <div className={styles.field}><Label htmlFor="policy-rule-id">规则 ID</Label><Input id="policy-rule-id" value={draft.id} maxLength={100} onChange={event => change('id', event.target.value)} className={styles.codeInput} /></div>
              <div className={styles.field}><Label htmlFor="policy-rule-extensions">文件扩展名</Label><Input id="policy-rule-extensions" value={draft.extensionsText} placeholder=".pdf, .docx, .html" onChange={event => change('extensionsText', event.target.value)} /><p>用逗号分隔；留空匹配任意类型。</p></div>
              <div className={styles.field}><Label htmlFor="policy-rule-regex">文件名匹配 <span>选填</span></Label><Input id="policy-rule-regex" value={draft.filenameRegex} maxLength={200} placeholder="例如：(?i)invoice|发票" onChange={event => change('filenameRegex', event.target.value)} className={styles.codeInput} /></div>
              <div className={styles.field}><Label htmlFor="policy-rule-parser">解析器</Label><Select value={draft.parserBackend || NONE} onValueChange={value => change('parserBackend', value === NONE ? '' : value)}><SelectTrigger id="policy-rule-parser"><SelectValue /></SelectTrigger><SelectContent><SelectItem value={NONE}>不覆盖默认配置</SelectItem>{draft.parserBackend && !PARSER_BACKEND_REGISTRY_OPTIONS.some(option => option.value === draft.parserBackend) ? <SelectItem value={draft.parserBackend}>{draft.parserBackend}</SelectItem> : null}{PARSER_BACKEND_REGISTRY_OPTIONS.map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}</SelectContent></Select></div>
              <div className={styles.field}><Label htmlFor="policy-rule-chunk">切块策略</Label><Select value={draft.chunkStrategy || NONE} onValueChange={value => change('chunkStrategy', value === NONE ? '' : value)}><SelectTrigger id="policy-rule-chunk"><SelectValue /></SelectTrigger><SelectContent><SelectItem value={NONE}>不覆盖默认配置</SelectItem>{draft.chunkStrategy && !c.chunkOptions.includes(draft.chunkStrategy) ? <SelectItem value={draft.chunkStrategy}>{draft.chunkStrategy}</SelectItem> : null}{c.chunkOptions.map(name => <SelectItem key={name} value={name}>{name}</SelectItem>)}</SelectContent></Select></div>
              <div className={styles.field}><Label htmlFor="policy-rule-profile">治理预设</Label><Select value={draft.governanceProfileRef || NONE} onValueChange={value => change('governanceProfileRef', value === NONE ? '' : value)}><SelectTrigger id="policy-rule-profile"><SelectValue /></SelectTrigger><SelectContent><SelectItem value={NONE}>不使用预设</SelectItem>{draft.governanceProfileRef && !profiles.some(profile => profile.value === draft.governanceProfileRef) ? <SelectItem value={draft.governanceProfileRef}>{draft.governanceProfileRef}</SelectItem> : null}{profiles.map(profile => <SelectItem key={profile.value} value={profile.value}>{profile.label}</SelectItem>)}</SelectContent></Select>{c.profilesQuery.isError ? <p className={styles.fieldError}>预设读取失败，已选值保留。<button type="button" onClick={() => { void c.profilesQuery.refetch() }}>重新读取</button></p> : null}</div>
              <div className={styles.enableField}><Label htmlFor="policy-rule-enabled">启用此规则</Label><Switch id="policy-rule-enabled" checked={draft.enabled} onCheckedChange={value => change('enabled', value)} /></div>
            </div>
          </TabsContent>
          <TabsContent value="preprocess" forceMount hidden={tab !== 'preprocess'} className={styles.tabPanel}>
            <div className={styles.preprocessHeading}><div><Label htmlFor="policy-preprocess-enabled">启用解析前预处理</Label><p>对原始文件执行所选步骤，再交给解析器。</p></div><Switch id="policy-preprocess-enabled" checked={draft.preprocessEnabled} onCheckedChange={value => change('preprocessEnabled', value)} /></div>
            <div className={styles.stepList}>{PREPROCESS_STEP_CATALOG.map(step => <label className={styles.stepRow} key={step.id} htmlFor={`policy-step-${step.id}`}><Checkbox id={`policy-step-${step.id}`} checked={draft.preprocessStepIds.includes(step.id)} disabled={!draft.preprocessEnabled} onCheckedChange={checked => change('preprocessStepIds', checked ? [...draft.preprocessStepIds, step.id] : draft.preprocessStepIds.filter(id => id !== step.id))} /><span><strong>{step.label}</strong><span>{step.desc}</span></span></label>)}</div>
          </TabsContent>
          <TabsContent value="advanced" forceMount hidden={tab !== 'advanced'} className={styles.tabPanel}><div className={styles.field}><Label htmlFor="policy-rule-patch">处理参数覆盖 <span>JSON，选填</span></Label><Textarea id="policy-rule-patch" value={draft.pipelinePatchJson} onChange={event => change('pipelinePatchJson', event.target.value)} placeholder={'{\n  "governance_enabled": true\n}'} className={styles.jsonInput} spellCheck={false} /><p>仅接受 DocumentPipelineOptions 支持的字段，服务端会校验。</p></div></TabsContent>
        </div>
      </Tabs>
      {error ? <p role="alert" className={styles.formError}>{error}</p> : null}
      <div className={styles.dialogFooter}><Button type="button" variant="ghost" onClick={() => c.setEditor(null)}>取消</Button><Button type="submit">{editor.originalId ? '应用修改' : '加入策略'}</Button></div>
    </form>
  </DialogContent></Dialog>
}

export function PolicyTemplateDialog({ c }: { c: IngestionPolicyController }) {
  const [selected, setSelected] = useState(INGESTION_POLICY_TEMPLATES[0]), [placement, setPlacement] = useState<TemplatePlacement>('prepend'), [error, setError] = useState('')
  return <Dialog open onOpenChange={open => { if (!open) c.setTemplatesOpen(false) }}><DialogContent className={styles.templatesDialog} onCloseAutoFocus={event => { event.preventDefault(); c.restoreFocus() }}>
    <DialogHeader className={styles.dialogHeader}><DialogTitle>从模板添加</DialogTitle><DialogDescription>选择规则组合及插入位置，保存策略后生效。</DialogDescription></DialogHeader>
    <div className={styles.templatesBody}><div className={styles.templateDirectory} role="group" aria-label="选择规则模板">{INGESTION_POLICY_TEMPLATES.map(template => <button type="button" key={template.key} aria-pressed={selected.key === template.key} onClick={() => { setSelected(template); setError('') }}><strong>{template.name}</strong><span>{template.rules.length} 条规则</span></button>)}</div>
      <section className={styles.templateDetails} aria-label="模板内容"><div className={styles.templatePicker}><Label htmlFor="policy-template-choice">规则模板</Label><Select value={selected.key} onValueChange={key => { setSelected(INGESTION_POLICY_TEMPLATES.find(template => template.key === key)!); setError('') }}><SelectTrigger id="policy-template-choice"><SelectValue /></SelectTrigger><SelectContent>{INGESTION_POLICY_TEMPLATES.map(template => <SelectItem key={template.key} value={template.key}>{template.name}</SelectItem>)}</SelectContent></Select></div><h3>{selected.name}</h3><p>{selected.description}</p><ol>{selected.rules.map((rule, index) => <li key={index}><strong>{rule.name}</strong><span>{rule.match?.extensions?.join(' · ') || '任意文件类型'}</span><span>{PARSER_BACKEND_REGISTRY_OPTIONS.find(option => option.value === rule.parser_backend)?.label ?? rule.parser_backend ?? '不覆盖默认解析器'}{rule.governance_profile_ref ? ` · ${rule.governance_profile_ref}` : ''}</span></li>)}</ol></section></div>
    {error ? <p className={styles.formError} role="alert">{error}</p> : null}
    <div className={styles.templateFooter}><div className={styles.field}><Label htmlFor="policy-template-placement">插入位置</Label><Select value={placement} onValueChange={value => { setPlacement(value as TemplatePlacement); setError('') }}><SelectTrigger id="policy-template-placement"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="prepend">添加到顶部</SelectItem><SelectItem value="append">添加到底部</SelectItem><SelectItem value="replace">替换全部规则</SelectItem></SelectContent></Select></div><span>{placement === 'replace' ? `将替换当前 ${c.rules.length} 条规则。` : `添加 ${selected.rules.length} 条规则。`}</span><Button disabled={c.blocked} onClick={() => { try { c.applyTemplate(selected, placement) } catch (cause) { setError(formatApiError(cause, '无法应用模板')) } }}>应用模板</Button></div>
  </DialogContent></Dialog>
}
