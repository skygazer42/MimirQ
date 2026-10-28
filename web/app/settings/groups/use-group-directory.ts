'use client'

import {useEffect,useMemo,useRef,useState} from 'react'
import {useQuery,useQueryClient} from '@tanstack/react-query'
import {toast} from 'sonner'
import {groupApi,rbacApi} from '@/lib/api/access'
import {useTenantAccess} from '@/hooks/use-tenant-access'
import {TENANT_PERMISSIONS,tenantAccessAllows} from '@/lib/tenant-permissions'
import {queryKeys} from '@/lib/query-keys'
import {formatApiError} from '@/lib/api-errors'
import type {TenantGroupOut,TenantGroupMemberOut} from '@/types/backend'
import {filterGroups,filterMembers,groupDraft,memberIds,memberIdentity,pageRows,parseGroupScope,readAll,writeGroupScope,type GroupScope} from './groups-model'

export const groupDirectoryKey=queryKeys.groups.list({scope:'directory-all'})
export const groupMemberKey=(id:string)=>queryKeys.groups.members(id,{scope:'directory-all'})
export const tenantIdentityKey=queryKeys.rbac.members({scope:'groups-identities-all'})
type Editor={mode:'create'|'edit';group:TenantGroupOut|null;name:string;external:string;errors:{name?:string;external?:string};error:string}
type Addition={group:TenantGroupOut;query:string;selected:string[];raw:string;error:string;limit:number}

export function useGroupDirectory() {
  const client=useQueryClient(),access=useTenantAccess()
  const canManage=tenantAccessAllows(access.data,TENANT_PERMISSIONS.SETTINGS_WRITE)
  const [scope,setScope]=useState(()=>parseGroupScope(typeof window==='undefined'?'':window.location.search))
  const scopeRef=useRef(scope),mounted=useRef(true)
  const [editor,setEditor]=useState<Editor|null>(null),[addition,setAddition]=useState<Addition|null>(null)
  const [deletion,setDeletion]=useState<TenantGroupOut|null>(null),[deleteError,setDeleteError]=useState('')
  const [busy,setBusy]=useState<string|null>(null),lock=useRef<string|null>(null),opener=useRef<HTMLElement|null>(null)
  useEffect(()=>{
    mounted.current=true
    const restore=()=>{const next=parseGroupScope(window.location.search);scopeRef.current=next;setScope(next);if(!lock.current){setEditor(null);setAddition(null);setDeletion(null)}}
    window.addEventListener('popstate',restore)
    return ()=>{mounted.current=false;window.removeEventListener('popstate',restore)}
  },[])
  function updateScope(patch:Partial<GroupScope>) {
    if(!mounted.current)return
    const next={...scopeRef.current,...patch};scopeRef.current=next;setScope(next);writeGroupScope(next)
  }
  const directoryQuery=useQuery({queryKey:groupDirectoryKey,queryFn:()=>readAll((skip,limit)=>groupApi.listGroups({skip,limit}),group=>group.id),staleTime:15_000,retry:false})
  const groups=useMemo(()=>directoryQuery.data??[],[directoryQuery.data])
  const selectedId=scope.groupId||groups[0]?.id||''
  const groupQuery=useQuery({queryKey:queryKeys.groups.detail(selectedId),enabled:Boolean(selectedId),queryFn:()=>groupApi.getGroup(selectedId),staleTime:15_000,retry:false})
  const membersQuery=useQuery({queryKey:groupMemberKey(selectedId),enabled:Boolean(selectedId),queryFn:()=>readAll((skip,limit)=>groupApi.listGroupMembers(selectedId,{skip,limit}),member=>member.user_id),staleTime:15_000,retry:false})
  const identitiesQuery=useQuery({queryKey:tenantIdentityKey,enabled:Boolean(selectedId),queryFn:()=>readAll((skip,limit)=>rbacApi.listTenantMembers({skip,limit}),member=>member.id),staleTime:30_000,retry:false})
  const group=groupQuery.data??groups.find(item=>item.id===selectedId)??null
  const members=useMemo(()=>membersQuery.data??[],[membersQuery.data]),identities=useMemo(()=>identitiesQuery.data??[],[identitiesQuery.data])
  const filtered=useMemo(()=>filterGroups(groups,scope),[groups,scope])
  const directoryPage=pageRows(filtered,scope.page,scope.size)
  const filteredMembers=useMemo(()=>filterMembers(members,scope.memberQuery,identities),[members,scope.memberQuery,identities])
  const membersPage=pageRows(filteredMembers,scope.memberPage,20)
  const currentIds=new Set(members.map(member=>member.user_id))
  const available=identities.filter(person=>Boolean(person.user_id)&&!currentIds.has(person.user_id!)).filter(person=>{
    const q=addition?.query.trim().toLocaleLowerCase()??''
    return !q||[person.username,person.email,person.user_id].some(value=>String(value??'').toLocaleLowerCase().includes(q))
  })
  const genuineEmpty=Boolean(directoryQuery.data)&&groups.length===0&&!directoryQuery.isError&&!selectedId
  function selectGroup(id:string) {if(!lock.current)updateScope({groupId:id,memberQuery:'',memberPage:1,view:'detail'})}
  function revealGroup() {
    const index=groups.findIndex(item=>item.id===selectedId)
    updateScope({query:'',external:'all',page:Math.floor(Math.max(index,0)/scope.size)+1,view:'directory'})
  }
  function begin(kind:string) {
    if(!canManage){toast.error('当前账号没有修改组的权限。');return false}
    if(lock.current){toast.info('上一项操作尚未完成。');return false}
    lock.current=kind;setBusy(kind);return true
  }
  function finish() {lock.current=null;if(mounted.current)setBusy(null)}
  function openEditor(mode:'create'|'edit',element:HTMLElement) {
    if(!canManage||lock.current||(mode==='edit'&&!group))return
    opener.current=element;setEditor({mode,group:mode==='edit'?group:null,name:mode==='edit'?group!.name:'',external:mode==='edit'?group!.external_id??'':'',errors:{},error:''})
  }
  function openAddition(element:HTMLElement) {
    if(!canManage||lock.current||!group)return
    toast.dismiss(`group-add:${group.id}`)
    opener.current=element;setAddition({group,query:'',selected:[],raw:'',error:'',limit:50})
  }
  function openDeletion(element:HTMLElement) {if(canManage&&!lock.current&&group){opener.current=element;setDeleteError('');setDeletion(group)}}
  function closeEditor() {if(!lock.current)setEditor(null)}
  function closeAddition() {if(!lock.current)setAddition(null)}
  function closeDeletion() {if(!lock.current)setDeletion(null)}
  function restoreFocus(event:Event) {
    event.preventDefault()
    requestAnimationFrame(()=>{
      const element=opener.current
      if(element?.isConnected&&!element.matches(':disabled'))element.focus()
      else document.querySelector<HTMLElement>('[data-groups-create],input[aria-label="搜索组"]')?.focus()
    })
  }
  async function saveEditor() {
    if(!editor||lock.current)return
    const captured=editor,{errors,payload}=groupDraft(captured.name,captured.external)
    if(Object.keys(errors).length){setEditor(previous=>previous?{...previous,errors,error:''}:null);document.getElementById(errors.name?'group-edit-name':'group-edit-external')?.focus();return}
    if(!begin(captured.mode))return
    setEditor(previous=>previous?{...previous,error:'',errors:{}}:null)
    try {
      const saved=captured.mode==='create'?await groupApi.createGroup(payload):await groupApi.patchGroup(captured.group!.id,payload)
      if(!mounted.current)return
      client.setQueryData(queryKeys.groups.detail(saved.id),saved)
      client.setQueryData<TenantGroupOut[]>(groupDirectoryKey,previous=>captured.mode==='create'?[...(previous??[]).filter(item=>item.id!==saved.id),saved]:(previous??[]).map(item=>item.id===saved.id?saved:item))
      await client.invalidateQueries({queryKey:groupDirectoryKey,exact:true})
      if(!mounted.current)return
      if(captured.mode==='create'){
        const all=client.getQueryData<TenantGroupOut[]>(groupDirectoryKey)??[],index=all.findIndex(item=>item.id===saved.id)
        updateScope({groupId:saved.id,query:'',external:'all',page:Math.floor(Math.max(0,index)/scopeRef.current.size)+1,memberQuery:'',memberPage:1,view:'detail'})
      }
      setEditor(null);toast.success(captured.mode==='create'?`已创建组「${saved.name}」`:`组「${saved.name}」信息已保存`)
    } catch(error){if(mounted.current)setEditor(previous=>previous?{...previous,error:formatApiError(error,'组信息保存失败，请重试。')}:null)}
    finally{finish()}
  }
  async function addMembers() {
    if(!addition||lock.current)return
    const captured=addition,{ids,error}=memberIds(captured.selected,captured.raw)
    if(error){setAddition(previous=>previous?{...previous,error}:null);return}
    if(!begin('add'))return
    setAddition(previous=>previous?{...previous,error:''}:null)
    try{
      const result=await groupApi.addGroupMembers(captured.group.id,{member_ids:ids})
      if(!mounted.current)return
      await client.invalidateQueries({queryKey:groupMemberKey(captured.group.id),exact:true})
      if(!mounted.current)return
      setAddition(null)
      if(result.updated>0)toast.success(`已向「${captured.group.name}」添加 ${result.updated} 名成员`,{id:`group-add:${captured.group.id}`})
      else toast.info('所选成员已在组内。')
    }catch(error){if(mounted.current)setAddition(previous=>previous?{...previous,error:formatApiError(error,'添加成员失败，请重试。')}:null)}
    finally{finish()}
  }
  async function restoreMember(target:TenantGroupOut,userId:string,label:string) {
    if(!begin('restore'))return
    try{await groupApi.addGroupMembers(target.id,{member_ids:[userId]});if(mounted.current)await client.invalidateQueries({queryKey:groupMemberKey(target.id),exact:true});toast.success(`已恢复成员「${label}」`)}
    catch(error){toast.error(formatApiError(error,'恢复成员失败，可重新添加。'))}finally{finish()}
  }
  async function removeMember(userId:string) {
    const target=group
    if(!target||!begin(`remove:${userId}`))return
    const who=memberIdentity(userId,identities)
    const index=members.findIndex(member=>member.user_id===userId),nextMember=members[index+1]??members[index-1]
    try{
      const result=await groupApi.removeGroupMembers(target.id,{member_ids:[userId]})
      if(!mounted.current)return
      client.setQueryData<TenantGroupMemberOut[]>(groupMemberKey(target.id),previous=>(previous??[]).filter(member=>member.user_id!==userId))
      await client.invalidateQueries({queryKey:groupMemberKey(target.id),exact:true})
      if(mounted.current&&result.updated>0)toast.success(`已从「${target.name}」移除 ${who.label}`,{action:{label:'撤销',onClick:()=>{void restoreMember(target,userId,who.label)}}})
      else if(mounted.current)toast.info('该成员已不在组内。')
      requestAnimationFrame(()=>{if(!mounted.current)return;const next=[...document.querySelectorAll<HTMLElement>('[data-group-member-action]')].find(element=>element.dataset.groupMemberAction===nextMember?.user_id);(next??document.querySelector<HTMLElement>('[data-groups-add]'))?.focus()})
    }catch(error){toast.error(formatApiError(error,'移除成员失败，请重试。'))}finally{finish()}
  }
  async function deleteGroup() {
    if(!deletion||!begin('delete'))return
    const target=deletion;setDeleteError('')
    try{
      await groupApi.deleteGroup(target.id)
      if(!mounted.current)return
      client.setQueryData<TenantGroupOut[]>(groupDirectoryKey,previous=>(previous??[]).filter(item=>item.id!==target.id))
      client.removeQueries({queryKey:queryKeys.groups.detail(target.id),exact:true})
      client.removeQueries({queryKey:groupMemberKey(target.id),exact:true})
      await client.invalidateQueries({queryKey:groupDirectoryKey,exact:true})
      if(!mounted.current)return
      updateScope({groupId:'',memberQuery:'',memberPage:1,view:'directory'});setDeletion(null);toast.success(`已删除组「${target.name}」`)
    }catch(error){if(mounted.current)setDeleteError(formatApiError(error,'删除组失败，请重试。'))}finally{finish()}
  }
  async function refresh() {
    await Promise.allSettled([directoryQuery.refetch(),...(selectedId?[groupQuery.refetch(),membersQuery.refetch(),identitiesQuery.refetch()]:[])])
  }
  async function copyId(value:string) {try{await navigator.clipboard.writeText(value);toast.success('ID 已复制')}catch{toast.error('复制失败，请选择 ID 后手动复制。')}}
  return {scope,updateScope,canManage,access,directoryQuery,groups,selectedId,groupQuery,group,membersQuery,members,identitiesQuery,identities,directoryPage,membersPage,available,currentIds,genuineEmpty,busy,
    selectGroup,revealGroup,editor,addition,deletion,deleteError,openEditor,openAddition,openDeletion,closeEditor,closeAddition,closeDeletion,restoreFocus,saveEditor,addMembers,removeMember,deleteGroup,refresh,copyId,
    changeEditor:(patch:Partial<Editor>)=>{if(!lock.current)setEditor(previous=>previous?{...previous,...patch}:null)},
    changeAddition:(patch:Partial<Addition>)=>{if(!lock.current)setAddition(previous=>previous?{...previous,...patch,...(patch.query!==undefined?{limit:50}:{})}:null)},
    refreshing:directoryQuery.isFetching||groupQuery.isFetching||membersQuery.isFetching||identitiesQuery.isFetching,
  }
}
export type GroupDirectoryController=ReturnType<typeof useGroupDirectory>
