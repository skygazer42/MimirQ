import type { TenantGroupOut,TenantGroupMemberOut } from '@/types/backend'
import type { TenantMember } from '@/lib/api/access'

export type GroupScope={query:string;external:'all'|'filled'|'empty';page:number;size:number;groupId:string;memberQuery:string;memberPage:number;view:'directory'|'detail'}
export function formatGroupDate(value:string|null|undefined,short=false) {
  if(!value)return '未记录'
  const date=new Date(value)
  if(Number.isNaN(date.getTime()))return value
  return new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',...(short?{}:{hour:'2-digit',minute:'2-digit',hour12:false})}).format(date).replace(/\//g,'-')
}
const positive=(value:string|null,fallback=1)=>value&&/^\d+$/.test(value)?Math.max(1,Math.min(1_000_000,Number(value))):fallback
export function parseGroupScope(search:string):GroupScope {
  const p=new URLSearchParams(search),size=Number(p.get('size'))
  return {query:p.get('q')??'',external:p.get('external')==='filled'?'filled':p.get('external')==='empty'?'empty':'all',page:positive(p.get('page')),size:[10,20,50].includes(size)?size:20,groupId:p.get('group')??'',memberQuery:p.get('mq')??'',memberPage:positive(p.get('mp')),view:p.get('view')==='directory'?'directory':p.get('view')==='detail'||p.has('group')?'detail':'directory'}
}
export function writeGroupScope(scope:GroupScope) {
  const url=new URL(window.location.href)
  const values:Record<string,string>={q:scope.query,external:scope.external==='all'?'':scope.external,page:scope.page===1?'':String(scope.page),size:scope.size===20?'':String(scope.size),group:scope.groupId,mq:scope.memberQuery,mp:scope.memberPage===1?'':String(scope.memberPage),view:scope.view}
  for(const [key,value] of Object.entries(values)){if(value)url.searchParams.set(key,value);else url.searchParams.delete(key)}
  window.history.replaceState(window.history.state,'',url)
}
export function filterGroups(groups:TenantGroupOut[],scope:Pick<GroupScope,'query'|'external'>) {
  const q=scope.query.trim().toLocaleLowerCase()
  return groups.filter(group=>(scope.external==='all'||Boolean(group.external_id?.trim())===(scope.external==='filled'))&&(!q||[group.name,group.external_id,group.id].some(value=>String(value??'').toLocaleLowerCase().includes(q))))
}
export function pageRows<T>(items:T[],page:number,size:number) {
  const pages=Math.max(1,Math.ceil(items.length/size)),current=Math.min(Math.max(1,page),pages)
  return {items:items.slice((current-1)*size,current*size),page:current,pages,total:items.length}
}
export function memberIdentity(userId:string,identities:TenantMember[]) {
  const person=identities.find(member=>member.user_id===userId)
  return {id:userId,label:person?.username?.trim()||person?.email?.trim()||userId,email:person?.email?.trim()||'',username:person?.username?.trim()||''}
}
export function filterMembers(members:TenantGroupMemberOut[],query:string,identities:TenantMember[]) {
  const q=query.trim().toLocaleLowerCase()
  return members.filter(member=>{const who=memberIdentity(member.user_id,identities);return !q||[who.id,who.label,who.email].some(value=>value.toLocaleLowerCase().includes(q))})
}
export function groupDraft(name:string,externalId:string) {
  const n=name.trim(),ext=externalId.trim()
  const errors:{name?:string;external?:string}={}
  if(!n)errors.name='请输入组名称。'
  else if(n.length>255)errors.name='组名称不能超过255个字符。'
  if(ext.length>255)errors.external='外部组 ID 不能超过255个字符。'
  return {errors,payload:{name:n,external_id:ext}}
}
export function memberIds(selected:string[],raw:string) {
  const ids=[...new Set([...selected,...raw.split(/[\n,;，；]+/)].map(value=>value.trim()).filter(Boolean))]
  const error=!ids.length?'请选择成员或填写成员 ID。':ids.length>200?'一次最多添加200名成员，请减少后重试。':ids.some(id=>id.length>255)?'成员 ID 不能超过255个字符。':''
  return {ids,error}
}
export async function readAll<T>(fetchPage:(skip:number,limit:number)=>Promise<{items?:T[];total:number}>,key:(item:T)=>string):Promise<T[]> {
  const result:T[]=[],seen=new Set<string>();let total:number|null=null
  for(let skip=0;;){
    const page=await fetchPage(skip,500)
    const items=page.items??(page.total===0?[]:undefined)
    if(!Array.isArray(items)||!Number.isSafeInteger(page.total)||page.total<0)throw new Error('目录响应不完整，请刷新后重试。')
    if(total!==null&&total!==page.total)throw new Error('目录在读取期间发生变化，请刷新后重试。')
    total=page.total
    if((!items.length&&result.length<total)||items.length>500)throw new Error('目录分页不完整，请刷新后重试。')
    for(const item of items){const id=key(item);if(!id||seen.has(id))throw new Error('目录分页出现重复，请刷新后重试。');seen.add(id);result.push(item)}
    if(result.length>total)throw new Error('目录数量不一致，请刷新后重试。')
    if(result.length===total)return result
    skip+=items.length
  }
}
