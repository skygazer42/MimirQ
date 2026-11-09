import fs from 'node:fs'
import path from 'node:path'
import { expect, type Page, type Route } from '@playwright/test'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'
import type { PromptTemplate } from '../lib/api/prompts'

type DesignTemplate = {key:string;name:string;description:string;content:string;variables:string[];category:string;tags:string[];version:number;system:boolean;active:boolean;usage:number}
const facts = JSON.parse(fs.readFileSync(path.resolve(__dirname, 'fixtures/prompts-table.json'), 'utf8')) as {templates:DesignTemplate[]}
export const evidence = path.resolve(__dirname, '../../artifacts/rebrand/prompts-table-v1/tests')
export function templates(): PromptTemplate[] {
  return facts.templates.map((t, i) => ({id:`prompt-${i}`,tenant_id:'tenant-fixture',template_key:t.key,name:t.name,description:t.description,content:t.content,variables:t.variables,category:t.category,tags:t.tags,is_system:t.system,is_active:t.active,usage_count:t.usage,version:t.version,parent_id:null,ab_experiment_key:null,ab_variant:null,ab_weight:1,created_at:'2026-10-24T08:30:00Z',updated_at:`2026-10-25T${String(20-Math.floor(i/60)).padStart(2,'0')}:${String(59-i%60).padStart(2,'0')}:00Z`}))
}
async function json(route:Route, value:unknown, status=200) {await route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)})}

export async function promptFixture(page:Page, theme:'light'|'dark'='light') {
  await page.setViewportSize({width:1600,height:1000})
  await installCommonApiMocks(page,{uploaded:false})
  await page.addInitScript(mode=>{localStorage.setItem('theme',mode);localStorage.setItem('mimirq.surfaceTheme','ocean');localStorage.setItem('mimirq.themeColor','#20262e')},theme)
  const state={items:templates(),failList:false,failSave:false,failId:'',canManage:true,inconsistentPages:false,saveGate:null as Promise<void>|null,listGate:null as Promise<void>|null,reads:[] as number[],writes:[] as Array<{method:string;path:string;body:Record<string,unknown>|null}>,errors:[] as string[]}
  page.on('pageerror',error=>state.errors.push(error.message))
  await page.route('**/api/v1/prompt-templates**',async route=>{
    const request=route.request(),url=new URL(request.url()),p=url.pathname,method=request.method()
    if(method==='GET'&&p==='/api/v1/prompt-templates') {
      state.reads.push(Number(url.searchParams.get('skip')||0))
      if(state.listGate)await state.listGate
      if(state.failList)return json(route,{detail:'模板服务暂不可用'},503)
      const skip=Number(url.searchParams.get('skip')||0),limit=Number(url.searchParams.get('limit')||50)
      const items=state.items.slice(skip,skip+limit)
      if(state.inconsistentPages&&skip>0&&items.length)items[0]=state.items[0]
      return json(route,{total:state.items.length,items})
    }
    if(method==='GET')return json(route,state.items.find(t=>p.endsWith(t.id))||{},200)
    const body=request.postDataJSON() as Record<string,unknown>|null
    state.writes.push({method,path:p,body})
    if(state.saveGate)await state.saveGate
    if(state.failSave)return json(route,{detail:'模板暂时无法保存'},503)
    if(p.endsWith('/builtins/sync'))return json(route,{created:0,updated:0,total:state.items.length})
    const target=state.items.find(t=>p.split('/')[4]===t.id)
    if(target?.id===state.failId)return json(route,{detail:'该模板暂时不可修改'},503)
    if(method==='POST'&&p.endsWith('/duplicate')&&target) {
      const copy={...target,id:`copy-${state.items.length}`,name:`${target.name} (副本)`,is_system:false,usage_count:0,updated_at:'2026-10-25T21:00:00Z'}
      state.items.unshift(copy);return json(route,copy,201)
    }
    if(method==='POST'&&p==='/api/v1/prompt-templates') {
      const item={...state.items[0],...body,id:`created-${state.items.length}`,is_system:false,updated_at:'2026-10-25T22:00:00Z'} as PromptTemplate
      state.items.unshift(item);return json(route,item,201)
    }
    if(target?.is_system&&(method==='PUT'||method==='DELETE'))return json(route,{detail:'Cannot modify system templates'},403)
    if(method==='PUT'&&target){Object.assign(target,body);return json(route,target)}
    if(method==='DELETE'&&target){state.items=state.items.filter(t=>t.id!==target.id);return route.fulfill({status:204})}
    return json(route,{detail:'Unexpected fixture request'},400)
  })
  // Never let an unhandled browser mutation reach the real local API.
  await page.route('**/api/v1/**',async route=>{
    if(new URL(route.request().url()).pathname==='/api/v1/rbac/me')return json(route,{tenant_id:'tenant-fixture',account_id:'fixture-user',role:state.canManage?'owner':'readonly',is_active:true,is_current:true,permissions:state.canManage?['settings.read','settings.write']:['settings.read']})
    if(route.request().url().includes('/prompt-templates'))return route.fallback()
    if(!['GET','HEAD','OPTIONS'].includes(route.request().method()))return json(route,{detail:'该操作未接入测试数据'},409)
    return route.fallback()
  })
  return state
}
export async function openPrompts(page:Page) {
  await page.goto('/prompts',{waitUntil:'domcontentloaded'})
  await expect(page.getByRole('heading',{name:/^提示词(模板)?$/,exact:true})).toBeVisible({timeout:60000})
}
export async function reloadPrompts(page:Page) {
  await page.reload({waitUntil:'domcontentloaded'})
  await expect(page.getByRole('heading',{name:/^提示词(模板)?$/,exact:true})).toBeVisible({timeout:60000})
}
export async function choose(page:Page,label:string,value:string) {
  await page.getByRole('combobox',{name:label,exact:true}).click()
  await page.getByRole('option',{name:value,exact:true}).click()
}
