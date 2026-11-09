import path from 'node:path'
import { expect,type Page,type Route } from '@playwright/test'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'
import type { PromptPreviewResponse } from '../types'

export const evidence=path.resolve(__dirname,process.env.DIAGNOSTICS_EVIDENCE_DIR??'../../artifacts/rebrand/diagnostics-workbench-v1/tests')
export const previewResponse={query_for_retrieval:'服务升级失败 回滚流程',prompt_messages:[],prompt_text:'请根据上下文回答：服务如何回滚？',variables:{context:'回滚前核对上一个稳定版本。'},citations:Array.from({length:6},(_,i)=>({document_id:i%2?'doc-b':'doc-a',content:`回滚检查 ${i+1}`})),metrics:{prompt_tokens:1248,context_tokens:936,history_tokens:128,elapsed_sec:.286}}
const ragDefaults={top_k:6,score_threshold:.2,retrieval_mode:'hybrid',retrieval_profile:'balanced',fusion_strategy:'rrf',enable_reranker:false}
export async function json(route:Route,body:unknown,status=200){await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)})}
export async function diagnosticFixture(page:Page,theme:'light'|'dark'='light') {
  await page.setViewportSize({width:1600,height:1000});await installCommonApiMocks(page,{uploaded:false})
  await page.addInitScript(mode=>{localStorage.setItem('theme',mode);localStorage.setItem('mimirq.surfaceTheme','ocean');localStorage.setItem('mimirq.themeColor','#20262e')},theme)
  const state={allow:true,failPreview:false,failExplain:false,failServices:false,backend:'milvus',preview:structuredClone(previewResponse) as PromptPreviewResponse,driftOverride:null as Record<string,unknown>|null,previewGate:null as Promise<void>|null,requests:[] as Array<{path:string;method:string;body:Record<string,unknown>|null;params:string}>,errors:[] as string[],consoleErrors:[] as string[]}
  page.on('pageerror',error=>state.errors.push(error.message))
  page.on('console',message=>{if(message.type()==='error')state.consoleErrors.push(message.text())})
  await page.route('**/api/v1/**',async route=>{
    const request=route.request(),url=new URL(request.url()),p=url.pathname,method=request.method()
    if(p==='/api/v1/rbac/me')return json(route,{tenant_id:'fixture',account_id:'fixture',role:'owner',permissions:state.allow?['observability.read','settings.read','settings.write']:[],is_active:true,is_current:true})
    if(p==='/api/v1/observability/frontend-vitals'||p==='/api/v1/observability/frontend-traces')return route.fulfill({status:204})
    if(p==='/api/v1/datasets'||p==='/api/v1/datasets/')return json(route,{total:2,items:[{id:'dataset-a',name:'工程文档库',document_count:128,rag_defaults:ragDefaults},{id:'dataset-b',name:'运维资料',document_count:2,rag_defaults:{}}]})
    if(p.startsWith('/api/v1/datasets/'))return json(route,{id:p.split('/').at(-1),name:p.endsWith('dataset-a')?'工程文档库':'运维资料',rag_defaults:p.endsWith('dataset-a')?ragDefaults:{}})
    if(p==='/api/v1/documents'||p==='/api/v1/documents/')return json(route,{total:2,items:[{id:'doc-a',filename:'服务发布规范.pdf',status:'completed',dataset_id:'dataset-a',file_type:'pdf'},{id:'doc-b',filename:'回滚清单.md',status:'completed',dataset_id:'dataset-a',file_type:'md'}]})
    if(p==='/api/v1/health/ready')return state.failServices?json(route,{detail:'服务检查暂不可用'},503):json(route,{ok:true,status:'ready'})
    if(p==='/api/v1/health')return json(route,{ok:true,status:'ok'})
    if(p==='/api/v1/health/details')return json(route,{ok:true,status:'ready',time:'2026-10-25T08:42:00Z',database:{status:'ready'},vector:{status:state.backend==='memory'?'disabled':'ready',backend:state.backend,required:state.backend!=='memory'},redis:{status:'disabled',enabled:false},minio:{status:'disabled',enabled:false}})
    if(p==='/api/v1/meta'||p==='/api/v1/meta/details')return json(route,{name:'Ragvia',build:{sha:'fixture'},api_version:'v1',time:'2026-10-25T08:42:00Z',features:{auth_mode:'header',vector_backend:state.backend}})
    if(p==='/api/v1/observability/diagnostics/deps')return json(route,{schema:'deps.v1',generated_at:'2026-10-25T08:42:00Z',postgres:{status:'ready'},milvus:{status:'ready'},redis:{status:'error',error:'disabled fixture service'},minio:{enabled:false}})
    if(p==='/api/v1/observability/online-quality/summary')return json(route,{enabled:false,recommendations:[]})
    if(p.endsWith('/prompt-preview')||p.endsWith('/explain')||p.endsWith('/config-hash')||p.endsWith('/embedding-drift/snapshot')||p.endsWith('/perf-suite/run')) {
      const body=method==='GET'?null:request.postDataJSON() as Record<string,unknown>|null
      state.requests.push({path:p,method,body,params:url.search})
      if(p.endsWith('/prompt-preview')){if(state.previewGate)await state.previewGate;return json(route,state.failPreview?{detail:'检索服务暂不可用'}:state.preview,state.failPreview?503:200)}
      if(p.endsWith('/explain'))return json(route,state.failExplain?{detail:'链路详情暂不可用'}:{channels:{counts:{vector_candidates:32,bm25_candidates:28,graph_candidates:3,sparse_candidates:0},timing:{vector_elapsed_sec:.15},retrieval_degraded:false,retrieval_degraded_reasons:[]},rerank:{used:false},stage_timings:{retrieval_elapsed_sec:.2},metrics:{}},state.failExplain?503:200)
      if(p.endsWith('/config-hash'))return json(route,{hash:'a8c91d72e164',effective_config:ragDefaults})
      if(p.endsWith('/embedding-drift/snapshot'))return json(route,state.driftOverride??(state.backend==='memory'?{ok:false,error:'unsupported_vector_backend',vector_backend:'memory'}:{ok:true,ts:'2026-10-25T08:42:00Z',vector_backend:'milvus',drift:{count:200,avg:.025,p50:.01,p95:.08},above_threshold:{count:24,ratio:.12},missing_vectors:0,dim_mismatch:0,sample_n_requested:200,threshold:.05}))
      return json(route,{schema:'mimirq.perf_suite_run.v1',baseline_ts:'2026-10-24T08:42:00Z',current_report:{iterations:10,cases:[{name:'health',method:'GET',path:'/api/v1/health',iterations:10,ok_count:10,ok_ratio:1,qps:42,latency_ms:{p50:12,p95:18,p99:20}},{name:'ready',method:'GET',path:'/api/v1/health/ready',iterations:10,ok_count:10,ok_ratio:1,qps:20,latency_ms:{p50:28,p95:90,p99:100}}]},diff:{strict_gate:{passed:false,regressions:1},cases:{health:{regressed:false},ready:{regressed:true,p95:{baseline_ms:30,current_ms:90,regressed:true}}}}})
    }
    if(!['GET','HEAD','OPTIONS'].includes(method))return json(route,{detail:'未拦截的测试写操作'},409)
    return route.fallback()
  })
  return state
}
export async function openDiagnostics(page:Page){await page.goto('/diagnostics',{waitUntil:'domcontentloaded'});await expect(page.getByRole('heading',{name:/^诊断(中心)?$/,exact:true})).toBeVisible({timeout:60000})}
