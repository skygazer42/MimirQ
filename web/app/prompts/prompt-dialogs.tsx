'use client'

import dynamic from 'next/dynamic'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Copy, Loader2 } from '@/components/icons'
import { promptDate, promptScenario } from './prompt-model'
import { PromptStatus, PromptVariables } from './prompt-table'
import type { PromptsController } from './use-prompt-templates'
import styles from './prompts.module.css'

const KgExtractPromptSettings=dynamic(()=>import('@/components/kg-extract-prompt-settings').then(m=>m.KgExtractPromptSettings),{loading:()=> <p className={styles.dialogLoading}>加载场景配置…</p>})
const KgPredicateOntologySettings=dynamic(()=>import('@/components/kg-predicate-ontology-settings').then(m=>m.KgPredicateOntologySettings),{loading:()=> <p className={styles.dialogLoading}>加载关系词表…</p>})

export function PromptDialogs({controller:c}:{controller:PromptsController}) {
  const t=c.preview
  return <>
    <Dialog open={c.editorOpen} onOpenChange={open=>{if(c.busy!=='save')c.setEditorOpen(open)}}>
      <DialogContent className={styles.editorDialog} onCloseAutoFocus={c.restoreFocus}>
        <form className={styles.dialogForm} onSubmit={event=>{event.preventDefault();void c.save()}}>
          <DialogHeader className={styles.dialogHeader}><DialogTitle>{c.editingTemplate?'编辑模板':'创建模板'}</DialogTitle><DialogDescription>用 {'{变量名}'} 标记需要传入的内容。</DialogDescription></DialogHeader>
          <div className={styles.dialogBody}>
            <fieldset disabled={Boolean(c.busy)} className={styles.formFields}>
              <div className={styles.field}><Label htmlFor="prompt-name">模板名称</Label><Input id="prompt-name" required maxLength={200} autoComplete="off" value={c.draft.name} onChange={event=>c.setDraft({...c.draft,name:event.target.value})} placeholder="例如：技术文档问答"/></div>
              <div className={styles.field}><Label htmlFor="prompt-description">用途说明 <span>选填</span></Label><Input id="prompt-description" value={c.draft.description} onChange={event=>c.setDraft({...c.draft,description:event.target.value})} placeholder="这个模板用于回答什么问题"/></div>
              <div className={styles.field}><Label htmlFor="prompt-content">模板正文</Label><Textarea id="prompt-content" className={styles.contentInput} required value={c.draft.content} onChange={event=>c.setDraft({...c.draft,content:event.target.value})} placeholder={'请根据 {context} 回答问题：{question}'} spellCheck={false}/></div>
              <div className={styles.twoFields}>
                <div className={styles.field}><Label htmlFor="prompt-variables">变量 <span>逗号分隔</span></Label><Input id="prompt-variables" value={c.draft.variablesText} onChange={event=>c.setDraft({...c.draft,variablesText:event.target.value})} placeholder="context, question, history" spellCheck={false}/></div>
                <div className={styles.field}><Label htmlFor="prompt-category">分类 <span>选填</span></Label><Input id="prompt-category" maxLength={100} value={c.draft.category} onChange={event=>c.setDraft({...c.draft,category:event.target.value})} placeholder="例如：rag_answer" list="prompt-categories"/><datalist id="prompt-categories">{c.categories.map(category=><option key={category} value={category}/>)}</datalist></div>
              </div>
              <div className={styles.field}><Label htmlFor="prompt-tags">标签 <span>选填，逗号分隔</span></Label><Input id="prompt-tags" value={c.draft.tagsText} onChange={event=>c.setDraft({...c.draft,tagsText:event.target.value})} placeholder="技术, 引用, 中文"/></div>
              <div className={styles.enableField}><Label htmlFor="prompt-active">启用模板</Label><Switch id="prompt-active" checked={c.draft.is_active} onCheckedChange={value=>c.setDraft({...c.draft,is_active:value})}/></div>
            </fieldset>
            {c.formError?<p className={styles.formError} role="alert">{c.formError}</p>:null}
          </div>
          <DialogFooter className={styles.dialogFooter}><Button type="button" variant="outline" disabled={c.busy==='save'} onClick={()=>c.setEditorOpen(false)}>取消</Button><Button type="submit" className={styles.primary} disabled={Boolean(c.busy)||!c.draft.name.trim()||!c.draft.content.trim()}>{c.busy==='save'?<Loader2 className="animate-spin"/>:null}{c.busy==='save'?'保存中':'保存模板'}</Button></DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
    <Dialog open={Boolean(t)} onOpenChange={open=>{if(!open)c.setPreview(null)}}>
      <DialogContent className={styles.previewDialog} onCloseAutoFocus={event=>{if(c.editorOpen)event.preventDefault();else c.restoreFocus(event)}}>
        {t?<>
          <DialogHeader className={styles.dialogHeader}><DialogTitle title={t.name}>{t.name}</DialogTitle><DialogDescription className="sr-only">模板用途、变量及正文</DialogDescription></DialogHeader>
          <div className={styles.dialogBody}>
            {t.name.length>70?<p className={styles.previewDescription}>{t.name}</p>:null}
            {t.description?<p className={styles.previewDescription}>{t.description}</p>:null}
            <dl className={styles.previewFacts}><div><dt>场景 / 分类</dt><dd>{promptScenario(t.category).label}<small>{t.category||'未分类'}</small></dd></div><div><dt>来源</dt><dd>{t.is_system?'内置 · 只读':'自定义'}</dd></div><div><dt>状态</dt><dd><PromptStatus template={t}/></dd></div><div><dt>使用次数</dt><dd>{t.usage_count.toLocaleString()}</dd></div></dl>
            <div className={styles.previewVariables}><h3>模板变量 <small>{t.variables.length} 个</small></h3><PromptVariables variables={t.variables}/></div>
            {t.tags.length?<div className={styles.previewTags}><h3>标签</h3><p>{t.tags.join(' · ')}</p></div>:null}
            <div className={styles.contentHeading}><h3>模板正文</h3><span>v{t.version} · {promptDate(t.updated_at,true)} 更新</span></div><pre className={styles.previewContent}>{t.content}</pre>
          </div>
          <DialogFooter className={styles.dialogFooter}><Button variant="outline" onClick={()=>c.setPreview(null)}>关闭</Button>{c.canManage&&!t.is_system?<Button variant="outline" disabled={Boolean(c.busy)} onClick={()=>c.openEditor(t)}>编辑模板</Button>:null}{c.canManage?<Button className={styles.primary} disabled={Boolean(c.busy)} onClick={()=>{void c.duplicate(t)}}>{c.busy===`copy:${t.id}`?<Loader2 className="animate-spin"/>:<Copy/>}复制为自定义模板</Button>:null}</DialogFooter>
        </>:null}
      </DialogContent>
    </Dialog>
    <AlertDialog open={c.deleteTargets.length>0} onOpenChange={open=>{if(!open&&!c.busy)c.closeDelete()}}>
      <AlertDialogContent className={styles.deleteDialog} onCloseAutoFocus={c.restoreFocus}>
        <AlertDialogHeader><AlertDialogTitle>删除{c.deleteTargets.length>1?` ${c.deleteTargets.length} 个`:''}模板？</AlertDialogTitle><AlertDialogDescription>{c.deleteTargets.length===1?`将删除「${c.deleteTargets[0].name}」。`:`将删除所选的 ${c.deleteTargets.length} 个自定义模板。`}此操作不可撤销。</AlertDialogDescription></AlertDialogHeader>
        {c.actionError?<p className={styles.formError} role="alert">{c.actionError}</p>:null}
        <AlertDialogFooter><AlertDialogCancel disabled={Boolean(c.busy)}>取消</AlertDialogCancel><Button variant="destructive" disabled={Boolean(c.busy)} onClick={()=>{void c.confirmDelete()}}>{c.busy==='delete'?<Loader2 className="animate-spin"/>:null}{c.busy==='delete'?'删除中':`删除${c.deleteTargets.length>1?` ${c.deleteTargets.length} 个模板`:'模板'}`}</Button></AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
    <Dialog open={c.bindingOpen} onOpenChange={c.setBindingOpen}>
      <DialogContent className={styles.bindingDialog} onCloseAutoFocus={c.restoreFocus}>
        <DialogHeader className={styles.dialogHeader}><DialogTitle>场景绑定</DialogTitle><DialogDescription>选择各场景使用的模板，维护知识图谱关系词表。</DialogDescription></DialogHeader>
        {c.bindingOpen?<Tabs defaultValue="templates" className={styles.bindingTabs}><TabsList className={styles.bindingTabList} aria-label="绑定配置类型"><TabsTrigger value="templates">场景模板</TabsTrigger><TabsTrigger value="predicates">关系词表</TabsTrigger></TabsList><TabsContent value="templates" className={styles.bindingBody}><KgExtractPromptSettings templates={c.templates}/></TabsContent><TabsContent value="predicates" className={styles.bindingBody}><KgPredicateOntologySettings/></TabsContent></Tabs>:null}
      </DialogContent>
    </Dialog>
  </>
}
