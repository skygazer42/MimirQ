import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const evidence=path.resolve(__dirname,'../../artifacts/rebrand/reports-overview-v1/tests')
async function json(route:Route,value:unknown,status=200) { await route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)}) }
function report(datasetId='dataset-a',hash='') {
  const empty=datasetId==='dataset-b', n=empty?0:hash?96:128
  return {
    dataset_id:datasetId,dataset_name:empty?'空数据集':'工程文档库',pipeline_hash:hash||null,generated_at:'2026-10-25T10:42:00Z',
    data_provenance:{source:'database',mocked:false,sections:{profile:'database'}},dataset_metadata:{},
    profile:{dataset_id:datasetId,generated_at:'2026-10-25T10:42:00Z',total_documents:n,total_size_bytes:empty?0:268854886,
      by_status:empty?{}:hash?{completed:90,parsing:3,failed:2,quarantined:1}:{completed:118,parsing:6,failed:3,quarantined:1},
      by_file_type:empty?{}:hash?{pdf:60,docx:20,md:12,xlsx:4}:{pdf:68,docx:32,md:20,xlsx:8},by_directory:empty?{}:{'/工程规范':n-6},
      file_size_histogram:[],length_percentiles:{p25:100,p50:400,p75:900,p90:1200,p99:2000},length_histogram:[],chunk_count_histogram:empty?[]:[{label:'1–10',count:n-5}],
      pdf_scan:{scanned:0,not_scanned:n,unknown:0},parsing_provenance:{docs_with_provenance:Math.max(0,n-3),by_resolved_backend:{},fallback_docs:0,elapsed_ms_percentiles:{}},pii_hits_total:{},secrets_hits_total:{},
      findings:empty?[]:[{key:'missing_directory',label:'目录字段缺失',severity:'warning',count:6,description:'有 6 个文档未记录目录字段。'},{key:'duplicate_hash',label:'重复文档',severity:'warning',count:4,description:'内容哈希重复。'},{key:'low_confidence',label:'低置信度内容',severity:'warning',count:5},{key:'parse_failed',label:'解析失败',severity:'error',count:hash?2:3},{key:'info',label:'扫描范围完整',severity:'info',count:0},{key:'zero_warning',label:'零命中规则',severity:'warning',count:0}]},
    compliance:{pii_hits_total:{email:7},secrets_hits_total:{},quarantined_documents:empty?0:1,failed_documents:empty?0:hash?2:3},
    pipeline_versions:empty?[]:hash?[{pipeline_hash:hash,documents:96}]:[{pipeline_hash:'9fd1bc3e6a2b',documents:96},{pipeline_hash:'4a8c017d9f32',documents:32}],
    connectors:empty?[]:[{id:'run-1',connector_id:'source-1',status:'failed',created_at:'2026-10-25T09:00:00Z',stats:{},error_message:'上游连接超时'}],
    retrieval_audit:empty?null:{status:'failed',plugin_refs:['engineering'],plugin_package_hashes:['package-abc'],failure_categories:{ranking:1},kg_recommendation:'none',recommended_next_action:'核对召回排序',gates:[{name:'召回门禁',status:'failed',metrics:{hit_at_1:.88,expected_metadata_hit_rate:.96,retrieval_effective_context_rate:.94,retrieval_noise_rate:.08},failed_conditions:['hit_at_1 < 0.90'],generated_at:'2026-10-25T10:40:00Z'}]}
  }
}
async function fixture(page:Page,theme:'light'|'dark'='light') {
  await page.setViewportSize({width:1600,height:1000})
  await installCommonApiMocks(page,{uploaded:false})
  await page.addInitScript(mode=>{localStorage.setItem('theme',mode);localStorage.setItem('mimirq.surfaceTheme','ocean');localStorage.setItem('mimirq.themeColor','#20262e')},theme)
  const state={failReport:false,failExport:false,reads:[] as string[],exports:[] as string[],writes:[] as string[],errors:[] as string[]}
  page.on('pageerror',error=>state.errors.push(error.message))
  await page.route('**/api/v1/**',async route=>{
    const request=route.request(),url=new URL(request.url()),p=url.pathname
    if((p==='/api/v1/datasets'||p==='/api/v1/datasets/')&&request.method()==='GET') return json(route,{total:2,items:[{id:'dataset-a',name:'工程文档库',document_count:128},{id:'dataset-b',name:'空数据集',document_count:0}]})
    if(p.includes('categor'))return json(route,{items:[]})
    if(!p.startsWith('/api/v1/reports/datasets/'))return route.fallback()
    if(request.method()!=='GET')state.writes.push(p)
    const id=p.split('/datasets/')[1].split('/')[0]
    if(p.includes('/export')||p.includes('/rag-audit/')) {
      state.exports.push(request.url())
      if(state.failExport)return json(route,{detail:'导出服务暂不可用'},503)
      return route.fulfill({status:200,contentType:p.endsWith('export-bundle')?'application/zip':p.endsWith('export')?'application/json':'text/html',body:p.endsWith('export')?JSON.stringify(report(id)):'<html>报告内容</html>'})
    }
    state.reads.push(request.url())
    return json(route,state.failReport?{detail:'报告服务暂不可用'}:report(id,url.searchParams.get('pipeline_hash')||''),state.failReport?503:200)
  })
  return state
}
async function open(page:Page) { await page.goto('/reports',{waitUntil:'domcontentloaded'});await expect(page.locator('[data-reports-overview]')).toBeVisible({timeout:60000}) }
test('A renders live report values, filters anomalies and exposes all report sections',async({page})=>{
  const state=await fixture(page);await open(page)
  await expect(page.getByRole('region',{name:'报告摘要'})).toContainText('128')
  await expect(page.getByRole('table',{name:'质量规则命中'})).toContainText('目录字段缺失')
  await page.getByRole('tab',{name:'数据质量',exact:true}).click()
  await expect(page.getByRole('table',{name:'质量规则命中'})).toContainText('扫描范围完整')
  await page.getByRole('checkbox',{name:'只看异常',exact:true}).check()
  await expect(page.getByRole('table',{name:'质量规则命中'})).not.toContainText('扫描范围完整')
  await expect(page.getByRole('table',{name:'质量规则命中'})).not.toContainText('零命中规则')
  await expect(page.getByText('密钥命中',{exact:true}).locator('..')).toContainText('待评估')
  await page.getByRole('tab',{name:'召回审计',exact:true}).click()
  await expect(page.getByText('hit_at_1 < 0.90',{exact:true})).toBeVisible()
  await page.getByRole('tab',{name:'结构与风险',exact:true}).click()
  await expect(page.getByRole('table',{name:'运行记录'})).toContainText('上游连接超时')
  await page.getByRole('tab',{name:'报告总览',exact:true}).click()
  await expect(page.getByRole('tab',{name:'报告总览',exact:true})).toHaveAttribute('aria-selected','true')
  await expect(page.getByRole('region',{name:'报告摘要'}).locator('..')).toHaveCSS('opacity','1')
  fs.mkdirSync(evidence,{recursive:true});await page.screenshot({path:`${evidence}/desktop-a.png`})
  expect(state.errors).toEqual([]);expect(state.writes).toEqual([])
})
test('version and run scope reach the original API, and report failure preserves selection for retry',async({page})=>{
  const state=await fixture(page);await open(page)
  await page.getByRole('combobox',{name:'处理版本',exact:true}).click();await page.getByRole('option',{name:/9fd1bc3e6a2b/}).click()
  await expect.poll(()=>state.reads.some(url=>new URL(url).searchParams.get('pipeline_hash')==='9fd1bc3e6a2b')).toBe(true)
  await expect(page.getByRole('region',{name:'报告摘要'})).toContainText('96')
  state.failReport=true
  await page.getByRole('combobox',{name:'附带运行记录',exact:true}).click();await page.getByRole('option',{name:'50 条记录',exact:true}).click()
  await expect(page.getByText('报告加载失败',{exact:true})).toBeVisible({timeout:20000})
  await expect(page.getByRole('combobox',{name:'处理版本',exact:true})).toContainText('9fd1bc3e6a2b')
  state.failReport=false;await page.getByRole('button',{name:'重试报告',exact:true}).click()
  await expect(page.getByRole('region',{name:'报告摘要'})).toBeVisible()
  await expect.poll(()=>state.reads.some(url=>new URL(url).searchParams.get('connector_runs_limit')==='50')).toBe(true)
  await page.getByRole('combobox',{name:'数据集',exact:true}).click();await page.getByRole('option',{name:'空数据集',exact:true}).click()
  await expect(page.getByRole('heading',{name:'该数据集还没有文档',exact:true})).toBeVisible()
  await expect(page.getByRole('combobox',{name:'处理版本',exact:true})).toContainText('全部处理版本')
  expect(state.writes).toEqual([])
})
test('all six exports stay available and redaction is sent only to HTML and ZIP; export failure retains settings',async({page})=>{
  const state=await fixture(page);await open(page)
  const menu=async()=>page.getByRole('button',{name:'导出报告',exact:true}).click()
  await menu();const firstDownload=page.waitForEvent('download');await page.getByRole('menuitem',{name:'导出 HTML',exact:true}).click();await firstDownload
  expect(new URL(state.exports.at(-1)!).searchParams.get('redact')).toBe('true')
  await menu();await page.getByRole('menuitemcheckbox',{name:'HTML／ZIP 脱敏',exact:true}).uncheck();await page.keyboard.press('Escape')
  await menu();const jsonDownload=page.waitForEvent('download');await page.getByRole('menuitem',{name:'导出 JSON',exact:true}).click();await jsonDownload
  expect(new URL(state.exports.at(-1)!).searchParams.has('redact')).toBe(false)
  for(const label of ['导出完整 JSON','导出 RAG 统计','导出 RAG 审计报告']) {
    await menu();const download=page.waitForEvent('download');await page.getByRole('menuitem',{name:label,exact:true}).click();await download
  }
  state.failExport=true;await menu();await page.getByRole('menuitem',{name:'导出数据包 ZIP',exact:true}).click()
  await expect(page.getByText('导出服务暂不可用',{exact:false}).first()).toBeVisible()
  state.failExport=false;await menu();await expect(page.getByRole('menuitemcheckbox',{name:'HTML／ZIP 脱敏',exact:true})).not.toBeChecked()
  const zipDownload=page.waitForEvent('download');await page.getByRole('menuitem',{name:'导出数据包 ZIP',exact:true}).click();await zipDownload
  expect(new URL(state.exports.at(-1)!).searchParams.get('redact')).toBe('false')
  expect(state.writes).toEqual([])
})
test('phone and dark appearance keep scope, tabs and report content reachable',async({page})=>{
  await fixture(page,'dark');await page.setViewportSize({width:390,height:844});await open(page)
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.getByRole('tab',{name:'召回审计',exact:true}).click();await expect(page.getByText('hit_at_1 < 0.90',{exact:true})).toBeVisible()
  await page.getByRole('tab',{name:'数据质量',exact:true}).click()
  const table=page.getByRole('table',{name:'质量规则命中'}),wrap=table.locator('..')
  await wrap.evaluate(element=>{element.scrollLeft=element.scrollWidth})
  const nameBox=await table.locator('tbody tr').first().locator('th').boundingBox(),wrapBox=await wrap.boundingBox()
  expect(nameBox!.x).toBeGreaterThanOrEqual(wrapBox!.x-1)
  expect(nameBox!.x).toBeLessThanOrEqual(wrapBox!.x+2)
  fs.mkdirSync(evidence,{recursive:true});await page.screenshot({path:`${evidence}/phone-rule-context.png`})
  await page.getByRole('tab',{name:'报告总览',exact:true}).click()
  await expect(page.getByRole('tab',{name:'报告总览',exact:true})).toHaveAttribute('aria-selected','true')
  await expect(page.getByRole('region',{name:'报告摘要'}).locator('..')).toHaveCSS('opacity','1')
  expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1)
  fs.mkdirSync(evidence,{recursive:true});await page.screenshot({path:`${evidence}/phone-dark.png`})
})
test('MRR and non-summary gates remain visible in audit details',async({page})=>{
  await fixture(page)
  let metrics:Record<string,unknown>={retrieval_mrr:.62,retrieval_ndcg:.71}
  await page.route('**/api/v1/reports/datasets/dataset-a?*',route=>json(route,{...report(),retrieval_audit:{status:'passed',plugin_refs:[],plugin_package_hashes:[],failure_categories:{},gates:[{name:'排序门禁',status:'passed',metrics,failed_conditions:[]}]}}))
  await open(page);await page.getByRole('tab',{name:'召回审计',exact:true}).click()
  await expect(page.getByRole('table',{name:'召回门禁指标'})).toContainText('0.620')
  metrics={probe_errors:2};await page.getByRole('button',{name:'刷新报告',exact:true}).click()
  await expect(page.getByText('当前门禁没有摘要指标，可展开门禁详情。',{exact:true})).toBeVisible()
  await expect(page.getByText('暂无召回审计记录',{exact:true})).toHaveCount(0)
  await page.getByText('排序门禁',{exact:true}).click();await page.getByText('原始门禁指标',{exact:true}).click()
  await expect(page.locator('pre')).toContainText('"probe_errors": 2')
})
