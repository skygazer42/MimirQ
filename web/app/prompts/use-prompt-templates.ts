'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { promptTemplateApi, type PromptTemplate, type PromptTemplateCreate } from '@/lib/api/prompts'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { useTenantAccess } from '@/hooks/use-tenant-access'
import { TENANT_PERMISSIONS, tenantAccessAllows } from '@/lib/tenant-permissions'
import { filterPrompts, INITIAL_FILTERS, PROMPT_SCENARIOS, promptScenario, splitPromptValues, type PromptFilters } from './prompt-model'

const EMPTY_TEMPLATES:PromptTemplate[] = []
export type PromptDraft = {name:string;description:string;content:string;variablesText:string;category:string;tagsText:string;is_active:boolean}
const EMPTY_DRAFT:PromptDraft = {name:'',description:'',content:'',variablesText:'',category:'',tagsText:'',is_active:true}

// Client-side content/tag search needs every API page, not only its first 100 rows.
async function loadTemplates() {
  const items:PromptTemplate[] = [], seen = new Set<string>()
  let skip=0, total=1
  while (skip < total) {
    const page = await promptTemplateApi.list({skip,limit:100})
    total = page.total
    if (!page.items.length && skip < total) throw new Error('模板列表未完整加载，请重试。')
    let added=0
    for (const template of page.items) if (!seen.has(template.id)) {seen.add(template.id);items.push(template);added++}
    if (!added && skip < total) throw new Error('模板列表未完整加载，请重试。')
    skip += page.items.length
  }
  if (items.length!==total) throw new Error('模板列表有变化，请重新加载。')
  return {items,total}
}

export function usePromptTemplates() {
  const queryClient = useQueryClient()
  const access=useTenantAccess()
  const canManage=tenantAccessAllows(access.data,TENANT_PERMISSIONS.SETTINGS_WRITE)
  const query = useQuery({queryKey:queryKeys.prompts.list({scope:'all'}),queryFn:loadTemplates})
  const templates = query.data?.items ?? EMPTY_TEMPLATES
  const [filters,setFilters] = useState<PromptFilters>(INITIAL_FILTERS)
  const [page,setPage] = useState(1)
  const [pageSize,setPageSize] = useState(20)
  const [selectedIds,setSelectedIds] = useState<Set<string>>(new Set())
  const [busy,setBusy] = useState('')
  const actionLock = useRef(false)
  const [actionError,setActionError] = useState('')
  const [editorOpen,setEditorOpen] = useState(false)
  const [editingTemplate,setEditingTemplate] = useState<PromptTemplate|null>(null)
  const [draft,setDraft] = useState<PromptDraft>(EMPTY_DRAFT)
  const [formError,setFormError] = useState('')
  const [preview,setPreview] = useState<PromptTemplate|null>(null)
  const [deleteTargets,setDeleteTargets] = useState<PromptTemplate[]>([])
  const [bindingOpen,setBindingOpen] = useState(false)
  const returnFocus = useRef<string|null>(null)

  const filtered = useMemo(()=>filterPrompts(templates,filters),[templates,filters])
  const totalPages = Math.max(1,Math.ceil(filtered.length/pageSize))
  const currentPage = Math.min(page,totalPages)
  const pageItems = filtered.slice((currentPage-1)*pageSize,currentPage*pageSize)
  const selectablePage = pageItems.filter(t=>!t.is_system)
  const selectedTemplates = canManage?filtered.filter(t=>!t.is_system && selectedIds.has(t.id)):[]
  const selectedCount = selectedTemplates.length
  const selectedPageCount = selectablePage.filter(t=>selectedIds.has(t.id)).length
  const counts = useMemo(()=>{
    const result:Record<string,number> = Object.fromEntries(PROMPT_SCENARIOS.map(s=>[s.key,0]))
    result.all=templates.length
    for (const t of templates) result[promptScenario(t.category).key]++
    return result
  },[templates])
  const categories = useMemo(()=>[...new Set(templates.map(t=>t.category).filter((v):v is string=>Boolean(v?.trim())))].sort(),[templates])

  useEffect(()=>{
    if (!query.isSuccess) return
    const valid = new Set(templates.filter(t=>!t.is_system).map(t=>t.id))
    setSelectedIds(previous=>{
      if ([...previous].every(id=>valid.has(id))) return previous
      return new Set([...previous].filter(id=>valid.has(id)))
    })
  },[templates,query.isSuccess])

  const changeFilter = <K extends keyof PromptFilters>(key:K,value:PromptFilters[K]) => {
    setFilters(previous=>({...previous,[key]:value,...(key==='scenario'?{category:'all'}:{})}))
    setPage(1);setSelectedIds(new Set());setActionError('')
  }
  const clearFilters = () => {setFilters(INITIAL_FILTERS);setPage(1);setSelectedIds(new Set());setActionError('')}
  const toggleOne = (template:PromptTemplate) => {
    if (!canManage || template.is_system || actionLock.current) return
    setSelectedIds(previous=>{const next=new Set(previous);if(next.has(template.id))next.delete(template.id);else next.add(template.id);return next})
  }
  const togglePage = () => {
    if (!canManage || actionLock.current) return
    const all = selectablePage.length>0 && selectedPageCount===selectablePage.length
    setSelectedIds(previous=>{const next=new Set(previous);for(const t of selectablePage){if(all)next.delete(t.id);else next.add(t.id)}return next})
  }
  const refresh = () => queryClient.invalidateQueries({queryKey:queryKeys.prompts.all})
  async function runAction(kind:string,action:()=>Promise<void>,onError?:(message:string)=>void) {
    if (!canManage){const message='当前账号没有管理模板的权限。';setActionError(message);onError?.(message);return}
    if (actionLock.current) return
    actionLock.current=true;setBusy(kind);setActionError('')
    try {await action()}
    catch(error){const message=formatApiError(error,'操作失败，请重试');setActionError(message);onError?.(message);toast.error(message)}
    finally {actionLock.current=false;setBusy('')}
  }
  const openEditor = (template?:PromptTemplate) => {
    if (!canManage || actionLock.current || template?.is_system) return
    returnFocus.current=template?.id??null
    setPreview(null);setEditingTemplate(template??null);setFormError('')
    setDraft(template ? {name:template.name,description:template.description??'',content:template.content,variablesText:template.variables.join(', '),category:template.category??'',tagsText:template.tags.join(', '),is_active:template.is_active} : {...EMPTY_DRAFT})
    setEditorOpen(true)
  }
  const save = async () => {
    if (!draft.name.trim() || !draft.content.trim()) {setFormError('请填写模板名称和正文。');return}
    const payload:PromptTemplateCreate = {name:draft.name.trim(),description:draft.description.trim(),content:draft.content,variables:splitPromptValues(draft.variablesText),category:draft.category.trim(),tags:splitPromptValues(draft.tagsText),is_active:draft.is_active}
    await runAction('save',async()=>{
      if (editingTemplate) await promptTemplateApi.update(editingTemplate.id,payload)
      else await promptTemplateApi.create(payload)
      await refresh();setEditorOpen(false);setFormError('');toast.success(editingTemplate?'模板已更新':'模板已创建')
    },setFormError)
  }
  const duplicate = (template:PromptTemplate) => runAction(`copy:${template.id}`,async()=>{
    await promptTemplateApi.duplicate(template.id);await refresh();toast.success('已复制为自定义模板')
  })
  const toggleActive = (template:PromptTemplate) => {
    if (template.is_system) return
    return runAction(`toggle:${template.id}`,async()=>{
      await promptTemplateApi.update(template.id,{is_active:!template.is_active});await refresh();toast.success(template.is_active?'模板已停用':'模板已启用')
    })
  }
  async function batch(targets:PromptTemplate[],kind:'activate'|'deactivate'|'delete') {
    const editable=targets.filter(t=>!t.is_system)
    if (!editable.length) return
    await runAction(kind,async()=>{
      const results=await Promise.allSettled(editable.map(t=>kind==='delete'?promptTemplateApi.delete(t.id):promptTemplateApi.update(t.id,{is_active:kind==='activate'})))
      const succeeded=editable.filter((_,i)=>results[i].status==='fulfilled'), failed=editable.filter((_,i)=>results[i].status==='rejected')
      const succeededIds=new Set(succeeded.map(t=>t.id))
      setSelectedIds(previous=>new Set([...previous].filter(id=>!succeededIds.has(id))))
      if(succeeded.length)await refresh()
      if(kind==='delete')setDeleteTargets(failed)
      const verb=kind==='delete'?'删除':kind==='activate'?'启用':'停用'
      if(failed.length){
        const failure=results.find(r=>r.status==='rejected') as PromiseRejectedResult
        const message=`${succeeded.length?`已${verb} ${succeeded.length} 个，`:''}${failed.length} 个模板未${verb}：${formatApiError(failure.reason,'请重试')}`
        setActionError(message);toast.error(message)
      }else toast.success(`已${verb} ${succeeded.length} 个模板`)
    })
  }
  const syncBuiltins = () => runAction('sync',async()=>{
    const result=await promptTemplateApi.syncBuiltins();await refresh();toast.success(`内置模板已同步：新增 ${result.created}，更新 ${result.updated}`)
  })

  return {query,templates,canManage,filters,changeFilter,clearFilters,categories,counts,filtered,pageItems,currentPage,totalPages,pageSize,setPage,
    changePageSize:(size:number)=>{setPageSize(size);setPage(1)},selectablePage,selectedIds,selectedTemplates,selectedCount,selectedPageCount,toggleOne,togglePage,
    clearSelection:()=>setSelectedIds(new Set()),busy,actionError,setActionError,editorOpen,setEditorOpen,editingTemplate,draft,setDraft,formError,openEditor,save,
    preview,setPreview,openPreview:(template:PromptTemplate)=>{returnFocus.current=template.id;setPreview(template)},deleteTargets,openDelete:(targets:PromptTemplate[])=>{returnFocus.current=targets.length===1?targets[0].id:null;setActionError('');setDeleteTargets(targets.filter(t=>!t.is_system))},closeDelete:()=>setDeleteTargets([]),
    confirmDelete:()=>batch(deleteTargets,'delete'),batchActive:(activate:boolean)=>batch(selectedTemplates,activate?'activate':'deactivate'),duplicate,toggleActive,syncBuiltins,bindingOpen,setBindingOpen,
    openBindings:()=>{returnFocus.current='bindings';setBindingOpen(true)},
    restoreFocus:(event:Event)=>{event.preventDefault();const id=returnFocus.current;requestAnimationFrame(()=>{const selector=id==='bindings'?'[data-prompt-bindings], [data-prompt-mobile-actions]':id?`[data-prompt-open="${CSS.escape(id)}"]`:'[data-prompt-create]';const target=[...document.querySelectorAll<HTMLElement>(selector)].find(element=>element.getClientRects().length>0);(target??document.querySelector<HTMLElement>('[data-prompt-create]'))?.focus()})}}
}
export type PromptsController = ReturnType<typeof usePromptTemplates>
