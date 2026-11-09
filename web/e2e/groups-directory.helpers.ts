import fs from 'node:fs'
import path from 'node:path'
import {expect,type Page,type Route} from '@playwright/test'
import {installCommonApiMocks} from './enterprise-quality-telemetry.helpers'
import type {TenantGroupOut,TenantGroupMemberOut} from '../types/backend'
import type {TenantMember} from '../lib/api/access'

type GroupFact={id:string;name:string;external_id:string|null;created_at:string;updated_at:string}
type PersonFact={user_id:string;username:string;email:string;created_at:string}
const facts=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../public/brand/explorations/groups-layouts-v1/facts.json'),'utf8')) as {groups:GroupFact[];selected_group_members:PersonFact[]}
const iso=(value:string)=>value.replace(' ','T')+':00+08:00'
export const evidence=path.resolve(__dirname,'../../artifacts/rebrand/groups-directory-v1/tests')
export const selectedGroupId=facts.groups[0].id
export function fixtureGroups():TenantGroupOut[]{return facts.groups.map(item=>({...item,tenant_id:'tenant-fixture',created_at:iso(item.created_at),updated_at:iso(item.updated_at)}))}
export function fixturePeople():TenantMember[]{
  const people=[...facts.selected_group_members,{user_id:'member-he',username:'季禾',email:'ji.he@example.com',created_at:'2026-10-20 10:20'},{user_id:'member-gu',username:'顾言',email:'gu.yan@example.com',created_at:'2026-10-20 10:20'},{user_id:'member-tang',username:'唐溪',email:'tang.xi@example.com',created_at:'2026-10-20 10:20'}]
  return people.map((person,index)=>({...person,id:`member-record-${index}`,tenant_id:'tenant-fixture',role:'viewer',is_active:true,is_current:false,created_at:iso(person.created_at),updated_at:iso(person.created_at)}))
}
async function json(route:Route,value:unknown,status=200){await route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)})}
export async function groupFixture(page:Page,theme:'light'|'dark'='light') {
  await page.setViewportSize({width:1600,height:1000});await installCommonApiMocks(page,{uploaded:false})
  await page.addInitScript(mode=>{localStorage.setItem('theme',mode);localStorage.setItem('mimirq.surfaceTheme','ocean');localStorage.setItem('mimirq.themeColor','#20262e')},theme)
  const memberships:Record<string,TenantGroupMemberOut[]>={}
  const groups=fixtureGroups(),people=fixturePeople()
  memberships[groups[0].id]=facts.selected_group_members.map(member=>({user_id:member.user_id,created_at:iso(member.created_at)}))
  memberships[groups[1].id]=[{user_id:'member-he',created_at:'2026-10-20T10:20:00+08:00'}]
  const state={groups,people,memberships,canRead:true,canManage:true,failList:false,failIdentities:false,failSave:false,failAdd:false,failDelete:false,failMemberRead:false,saveGate:null as Promise<void>|null,detailGates:{} as Partial<Record<string,Promise<void>>>,reads:[] as Array<{path:string;skip:number}>,writes:[] as Array<{path:string;method:string;body:Record<string,unknown>|null}>,blocked:[] as string[],errors:[] as string[]}
  page.on('pageerror',error=>state.errors.push(error.message))
  await page.addInitScript(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async(value:string)=>{(window as unknown as {groupCopiedId:string}).groupCopiedId=value}}})})
  await page.route('**/api/v1/**',async route=>{
    const request=route.request(),url=new URL(request.url()),p=url.pathname.replace(/\/$/,''),method=request.method(),skip=Number(url.searchParams.get('skip')||0),limit=Number(url.searchParams.get('limit')||500)
    if(p==='/api/v1/rbac/me')return json(route,{tenant_id:'tenant-fixture',account_id:'fixture-user',role:'admin',is_active:true,is_current:true,permissions:state.canRead?(state.canManage?['settings.read','settings.write']:['settings.read']):[]})
    if(p.startsWith('/api/v1/observability/frontend'))return route.fulfill({status:204})
    if(p==='/api/v1/rbac/members'){
      state.reads.push({path:p,skip});return state.failIdentities?json(route,{detail:'成员目录暂不可用'},503):json(route,{total:state.people.length,items:state.people.slice(skip,skip+limit)})
    }
    if(p==='/api/v1/groups'||p.startsWith('/api/v1/groups/')){
      if(method==='GET'){
        state.reads.push({path:p,skip})
        if(p==='/api/v1/groups')return state.failList?json(route,{detail:'组目录暂不可用'},503):json(route,{total:state.groups.length,items:state.groups.slice(skip,skip+limit)})
        const id=decodeURIComponent(p.split('/')[4]),group=state.groups.find(item=>item.id===id)
        if(!group)return json(route,{detail:'Group not found'},404)
        if(p.endsWith('/members'))return state.failMemberRead?json(route,{detail:'组成员暂不可用'},503):json(route,{total:(state.memberships[id]??[]).length,items:(state.memberships[id]??[]).slice(skip,skip+limit)})
        const captured=structuredClone(group)
        if(state.detailGates[id])await state.detailGates[id]
        return json(route,captured)
      }
      const body=method==='DELETE'?null:request.postDataJSON() as Record<string,unknown>
      state.writes.push({path:p,method,body})
      if(!state.canManage)return json(route,{detail:'No permission to manage groups'},403)
      if(state.saveGate)await state.saveGate
      if(p==='/api/v1/groups'&&method==='POST'){
        if(state.failSave)return json(route,{detail:'组信息暂时无法保存'},503)
        if(state.groups.some(group=>group.name===body!.name))return json(route,{detail:'Group name already exists'},409)
        const created:TenantGroupOut={id:`61ed0c72-6419-4eac-a538-${String(state.groups.length+1).padStart(12,'0')}`,tenant_id:'tenant-fixture',name:String(body!.name),external_id:String(body!.external_id||'')||null,created_at:'2026-10-26T15:00:00+08:00',updated_at:'2026-10-26T15:00:00+08:00'}
        state.groups.push(created);state.memberships[created.id]=[];return json(route,created,201)
      }
      const id=decodeURIComponent(p.split('/')[4]),group=state.groups.find(item=>item.id===id)
      if(!group)return json(route,{detail:'Group not found'},404)
      if(method==='PATCH'){
        if(state.failSave)return json(route,{detail:'组信息暂时无法保存'},503)
        if(typeof body?.name==='string')group.name=body.name
        if(body?.external_id!==null&&body?.external_id!==undefined)group.external_id=String(body.external_id).trim()||null
        group.updated_at='2026-10-26T16:00:00+08:00';return json(route,group)
      }
      if(method==='DELETE'){
        if(state.failDelete)return json(route,{detail:'该组暂时无法删除'},503)
        state.groups=state.groups.filter(item=>item.id!==id);delete state.memberships[id];return route.fulfill({status:204})
      }
      if(method==='POST'&&(p.endsWith('/members')||p.endsWith('/members/remove'))){
        if(state.failAdd)return json(route,{detail:'成员暂时无法添加'},503)
        const ids=body!.member_ids as string[],current=state.memberships[id]??[]
        if(p.endsWith('/remove')){const next=current.filter(member=>!ids.includes(member.user_id));state.memberships[id]=next;return json(route,{updated:current.length-next.length})}
        const missing=ids.filter(uid=>!state.people.some(person=>person.user_id===uid))
        if(missing.length)return json(route,{detail:`Unknown tenant members: ${missing.join(', ')}`},400)
        const additions=ids.filter(uid=>!current.some(member=>member.user_id===uid)).map(user_id=>({user_id,created_at:'2026-10-26T15:00:00+08:00'}))
        state.memberships[id]=[...current,...additions];return json(route,{updated:additions.length})
      }
      return json(route,{detail:'未识别的组测试操作'},409)
    }
    if(!['GET','HEAD','OPTIONS'].includes(method)){state.blocked.push(`${method} ${p}`);return json(route,{detail:'未拦截的测试写操作'},409)}
    return route.fallback()
  })
  return state
}
export async function openGroups(page:Page,url=`/settings/groups?group=${selectedGroupId}`){await page.goto(url,{waitUntil:'domcontentloaded'});await expect(page.locator('[data-groups-directory]')).toBeVisible({timeout:60000});await expect(page.getByRole('button',{name:'刷新组',exact:true})).toBeEnabled({timeout:30000})}
export async function reloadGroups(page:Page){await page.reload({waitUntil:'domcontentloaded'});await expect(page.locator('[data-groups-directory]')).toBeVisible({timeout:60000});await expect(page.getByRole('button',{name:'刷新组',exact:true})).toBeEnabled({timeout:30000})}
