'use client'

import {Button} from '@/components/ui/button'
import {Input} from '@/components/ui/input'
import {Textarea} from '@/components/ui/textarea'
import {Label} from '@/components/ui/label'
import {Checkbox} from '@/components/ui/checkbox'
import {SearchInput} from '@/components/ui/search-input'
import {Dialog,DialogContent,DialogDescription,DialogHeader,DialogTitle} from '@/components/ui/dialog'
import {AlertDialog,AlertDialogContent,AlertDialogDescription,AlertDialogHeader,AlertDialogTitle,AlertDialogAction,AlertDialogCancel} from '@/components/ui/alert-dialog'
import {Loader2} from '@/components/icons'
import {memberIdentity,memberIds} from './groups-model'
import type {GroupDirectoryController} from './use-group-directory'
import styles from './groups.module.css'

export function GroupDialogs({controller:c}:{controller:GroupDirectoryController}) {
  const edit=c.editor,add=c.addition,disabled=Boolean(c.busy)||!c.canManage
  return <>
    <Dialog open={Boolean(edit)} onOpenChange={open=>{if(!open)c.closeEditor()}}><DialogContent className={styles.editDialog} onCloseAutoFocus={c.restoreFocus} onEscapeKeyDown={event=>{if(c.busy)event.preventDefault()}} onInteractOutside={event=>{if(c.busy)event.preventDefault()}}>
      <DialogHeader><DialogTitle>{edit?.mode==='create'?'新建组':'编辑组信息'}</DialogTitle><DialogDescription>{edit?.mode==='create'?'创建后可以添加当前租户的已有成员。':'修改当前组的名称或外部标识。'}</DialogDescription></DialogHeader>
      <form onSubmit={event=>{event.preventDefault();void c.saveEditor()}} noValidate className={styles.dialogForm}>
        <div className={styles.dialogBody}>
          <div className={styles.formField}><Label htmlFor="group-edit-name">组名称</Label><Input id="group-edit-name" value={edit?.name??''} maxLength={255} autoComplete="off" disabled={disabled} onChange={event=>c.changeEditor({name:event.target.value})} aria-invalid={Boolean(edit?.errors.name)} aria-describedby={edit?.errors.name?'group-name-error':undefined}/>{edit?.errors.name?<p role="alert" id="group-name-error" className={styles.fieldError}>{edit.errors.name}</p>:null}</div>
          <div className={styles.formField}><Label htmlFor="group-edit-external">外部组 ID <span>选填</span></Label><Input id="group-edit-external" value={edit?.external??''} maxLength={255} autoComplete="off" disabled={disabled} onChange={event=>c.changeEditor({external:event.target.value})} aria-invalid={Boolean(edit?.errors.external)} aria-describedby={edit?.errors.external?'group-external-error':'group-external-hint'}/><p id="group-external-hint" className={styles.fieldHint}>用于关联外部组标识，填写后不代表已完成同步。</p>{edit?.errors.external?<p role="alert" id="group-external-error" className={styles.fieldError}>{edit.errors.external}</p>:null}</div>
          {edit?.error?<p role="alert" className={styles.domainError}>{edit.error}</p>:null}
        </div>
        <div className={styles.dialogFooter}><Button type="button" variant="outline" disabled={Boolean(c.busy)} onClick={c.closeEditor}>取消</Button><Button type="submit" className={styles.primary} disabled={disabled}>{c.busy?<Loader2 className="animate-spin motion-reduce:animate-none"/>:null}{c.busy?(edit?.mode==='create'?'创建中':'保存中'):edit?.mode==='create'?'创建组':'保存修改'}</Button></div>
      </form>
    </DialogContent></Dialog>

    <Dialog open={Boolean(add)} onOpenChange={open=>{if(!open)c.closeAddition()}}><DialogContent className={styles.addDialog} onCloseAutoFocus={c.restoreFocus} onEscapeKeyDown={event=>{if(c.busy)event.preventDefault()}} onInteractOutside={event=>{if(c.busy)event.preventDefault()}}>
      <DialogHeader><DialogTitle>添加成员</DialogTitle><DialogDescription>选择当前租户的已有成员。</DialogDescription></DialogHeader>
      <form className={styles.dialogForm} noValidate onSubmit={event=>{event.preventDefault();void c.addMembers()}}>
        <div className={styles.dialogBody}>
          <p className={styles.dialogTarget}>目标组：<strong>{add?.group.name}</strong></p>
          <SearchInput aria-label="搜索可添加成员" value={add?.query??''} onValueChange={query=>c.changeAddition({query})} disabled={disabled} placeholder="搜索姓名、邮箱或成员 ID" inputClassName={styles.pickerSearch}/>
          {c.identitiesQuery.isPending?<p className={styles.inlineState} role="status">正在读取成员目录…</p>:c.identitiesQuery.isError?<p className={styles.domainError} role="alert">成员目录获取失败，仍可使用成员 ID 添加。<button type="button" onClick={()=>{void c.identitiesQuery.refetch()}}>重试</button></p>:<div className={styles.pickerList} aria-label="可添加成员">
            {c.available.length?c.available.slice(0,add?.limit??50).map(person=>{const id=person.user_id!,who=memberIdentity(id,c.identities),checked=add?.selected.includes(id)??false;return <label className={styles.pickerRow} key={person.id}><Checkbox checked={checked} disabled={disabled||Boolean(!checked&&add&&add.selected.length>=200)} onCheckedChange={()=>c.changeAddition({selected:checked?add!.selected.filter(value=>value!==id):[...add!.selected,id]})} aria-label={`选择 ${who.label}`}/><span><strong>{who.label}</strong><small>{who.email&&who.email!==who.label?who.email:id}</small></span></label>}):<p className={styles.inlineState}>{add?.query?'没有匹配的可添加成员。':'没有可添加的成员。'}</p>}
            {c.available.length>(add?.limit??50)?<Button type="button" variant="ghost" disabled={disabled} className={styles.moreMembers} onClick={()=>c.changeAddition({limit:(add?.limit??50)+50})}>显示更多成员（剩余 {c.available.length-(add?.limit??50)}）</Button>:null}
          </div>}
          <details className={styles.manualIds} open={c.identitiesQuery.isError||undefined}><summary>按成员 ID 添加</summary><Label htmlFor="group-add-ids">成员 ID</Label><Textarea id="group-add-ids" value={add?.raw??''} onChange={event=>c.changeAddition({raw:event.target.value})} rows={4} disabled={disabled} placeholder="每行一个，或使用逗号分隔"/><p className={styles.fieldHint}>一次最多200名，只能添加当前租户已有的成员。</p></details>
          {add?.error?<p role="alert" className={styles.domainError}>{add.error}</p>:null}
        </div>
        <div className={styles.dialogFooter}><span>已选 {memberIds(add?.selected??[],add?.raw??'').ids.length} / 200</span><Button type="button" variant="outline" disabled={Boolean(c.busy)} onClick={c.closeAddition}>取消</Button><Button type="submit" className={styles.primary} disabled={disabled}>{c.busy?<Loader2 className="animate-spin motion-reduce:animate-none"/>:null}{c.busy?'添加中':'添加成员'}</Button></div>
      </form>
    </DialogContent></Dialog>

    <AlertDialog open={Boolean(c.deletion)} onOpenChange={open=>{if(!open)c.closeDeletion()}}><AlertDialogContent className={styles.deleteDialog} onCloseAutoFocus={c.restoreFocus}>
      <AlertDialogHeader><AlertDialogTitle>删除组？</AlertDialogTitle><AlertDialogDescription>该组及其成员关系会被删除，成员账号不受影响。此操作无法撤销。</AlertDialogDescription></AlertDialogHeader>
      <div className={styles.dialogBody}><p className={styles.dialogTarget}>组名称：<strong>{c.deletion?.name}</strong></p>{c.deleteError?<p role="alert" className={styles.domainError}>{c.deleteError}</p>:null}</div>
      <div className={styles.dialogFooter}><AlertDialogCancel disabled={Boolean(c.busy)} onClick={c.closeDeletion}>取消</AlertDialogCancel><AlertDialogAction disabled={disabled} onClick={event=>{event.preventDefault();void c.deleteGroup()}}>{c.busy?<Loader2 className="animate-spin motion-reduce:animate-none"/>:null}{c.busy?'删除中':'删除组'}</AlertDialogAction></div>
    </AlertDialogContent></AlertDialog>
  </>
}
