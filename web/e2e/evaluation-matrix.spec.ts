import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/evaluation-matrix-v1/tests')
const metricKeys = ['faithfulness', 'response_relevancy', 'context_precision']
const scores = [[.96,.94,.91],[.91,.93,.88],[.88,.92,.87],[.89,.9,.83],[.42,.78,.63],[.86,.89,.81],[.93,.95,.9],[.78,.84,.76]]
const question = '只增加代码生成量，就能达到高级工程师要求吗？'
const questions = ['系统架构设计能力包含哪些方面？','初级与高级工程师的架构职责有什么区别？','知识资产化的主要工作是什么？','代码审核需要关注哪些问题？',question,'如何提升团队的交付质量？','技术债务应该怎样识别和治理？','团队知识库与个人经验有什么关系？']
async function json(route: Route, body: unknown, status=200) { await route.fulfill({ status, contentType:'application/json', body:JSON.stringify(body) }) }
async function fixture(page: Page, options: { empty?: boolean; theme?: 'light' | 'dark' } = {}) {
  await page.setViewportSize({width:1600,height:1000})
  await installCommonApiMocks(page, { uploaded:false })
  await page.addInitScript(theme => { localStorage.setItem('theme',theme); localStorage.setItem('mimirq.surfaceTheme','ocean'); localStorage.setItem('mimirq.themeColor','#20262e') }, options.theme || 'light')
  const runs = ['run-a','run-b'].map((id,i) => ({ id, conversation_id:'conv-a', status:'completed', metrics:metricKeys, params:{ max_turns:20, skip_empty_contexts:true }, summary:{ faithfulness:.83,response_relevancy:.89,context_precision:.82,items:8 }, created_at:`2026-10-25T${i ? '09':'10'}:42:00Z`, started_at:'2026-10-25T10:42:00Z', finished_at:'2026-10-25T10:42:22Z' }))
  const items = scores.map((values,i) => ({ id:`item-${i+1}`, run_id:'run-a', turn_index:i+1, user_input:questions[i], response:i===4?'高级工程师主要以代码生成量与自动化比例作为衡量标准。':`回答 ${i+1}`, retrieved_contexts:[`引用 ${i+1}：能够主导建立跨模块的系统架构规范与复用标准。`], citations:[{content:`引用 ${i+1}`,document_id:'source-doc',document_name:'工程能力标准'}], scores:Object.fromEntries(metricKeys.map((key,j)=>[key,values[j]])),created_at:'2026-10-25T10:42:22Z' }))
  const state = { failStart:false, failDetail:false, posts:[] as Record<string,unknown>[], writes:[] as string[], errors:[] as string[] }
  page.on('pageerror',error=>state.errors.push(error.message))
  await page.route('**/api/v1/**', async route => {
    const request=route.request(); const url=new URL(request.url()); const p=url.pathname
    if (p==='/api/v1/chat/conversations') return json(route,{total:2,items:[{id:'conv-a',title:'工程能力问答',message_count:16,created_at:'2026-10-25T09:00:00Z'},{id:'conv-missing',title:'缺少引用的对话',message_count:2,created_at:'2026-10-24T09:00:00Z'}]})
    if (p.endsWith('/messages')) return json(route,{messages:[{id:'assistant',role:'assistant',content:'原始回答',citations:p.includes('conv-missing')?[]:[{content:'原始证据'}]}]})
    if (p.endsWith('/conversation-readiness')) return json(route,{total:2,items:[{conversation_id:'conv-a',assistant_turns:8,evaluable_turns:8,citations_count:8,is_evaluable:true},{conversation_id:'conv-missing',assistant_turns:1,evaluable_turns:0,citations_count:0,is_evaluable:false}]})
    if (p==='/api/v1/evaluations/ragas/runs' && request.method()==='POST') {
      const payload=request.postDataJSON(); state.posts.push(payload)
      return json(route,state.failStart?{detail:'评测服务暂不可用'}:{...runs[0],id:'run-new',status:'pending'},state.failStart?503:200)
    }
    if (p==='/api/v1/evaluations/ragas/runs') return json(route,{total:options.empty?0:2,items:options.empty||url.searchParams.get('conversation_id')==='conv-missing'?[]:runs})
    if (p.startsWith('/api/v1/evaluations/ragas/runs/')) {
      const id=p.split('/').at(-1)!
      if (state.failDetail) return json(route,{detail:'无法读取运行结果'},503)
      return json(route,{run:{...runs.find(run=>run.id===id)||runs[0],id},items:id==='run-b'?[{...items[0],id:'other-item',run_id:id,user_input:'另一轮运行的问题',response:'另一轮的回答',retrieved_contexts:['另一轮的证据']}]:items})
    }
    if ((p==='/api/v1/datasets'||p==='/api/v1/datasets/')&&request.method()==='GET') return json(route,{total:1,items:[{id:'dataset-a',name:'工程文档',document_count:1,created_at:'2026-10-25T09:00:00Z'}]})
    if (p.startsWith('/api/v1/evaluations/ragas/regression/')) {
      if(request.method()!=='GET') state.writes.push(p)
      return json(route,{total:0,items:[]})
    }
    if (p.startsWith('/api/v1/observability/queryset-health/')) return json(route,{total:0,items:[],timeseries:{ts_ms:[],hit_at_k:[],mrr:[],ndcg_at_k:[],p95_latency_ms:[],miss_rate:[],weak_hit_rate:[]}})
    return route.fallback()
  })
  return state
}
async function open(page: Page, query='') { await page.goto(`/evaluations${query}`,{waitUntil:'domcontentloaded'}); await expect(page.locator('[data-evaluation-matrix]')).toBeVisible({timeout:60000}) }
test('C reviews actual per-item scores, filters low samples and isolates evidence across runs',async({page})=>{
  const state=await fixture(page); await open(page)
  const matrix=page.getByRole('table',{name:'逐轮评分矩阵'})
  await expect(matrix.getByRole('button',{name:question,exact:true})).toBeVisible()
  await matrix.getByRole('button',{name:question,exact:true}).click()
  await expect(page.getByRole('region',{name:'样本阅读区'})).toContainText('引用 5：')
  fs.mkdirSync(evidence,{recursive:true}); await page.screenshot({path:`${evidence}/desktop-c.png`})
  await page.getByRole('button',{name:/低分.*2/}).click()
  await expect(matrix.locator('tbody tr[data-sample-row]')).toHaveCount(2)
  await page.getByRole('searchbox',{name:'搜索评测问题'}).fill('不存在的内容')
  await expect(page.getByText('没有匹配的样本', {exact:true})).toBeVisible()
  await page.getByRole('searchbox',{name:'搜索评测问题'}).fill('')
  await page.getByRole('button',{name:/运行记录/}).click()
  await page.getByRole('dialog',{name:'运行记录'}).getByRole('button',{name:/run-b/}).click()
  await expect(page.getByRole('region',{name:'样本阅读区'})).toContainText('另一轮的证据')
  await expect(page.getByRole('region',{name:'样本阅读区'})).not.toContainText('引用 5：')
  await page.screenshot({path:`${evidence}/run-scope.png`})
  expect(state.posts).toEqual([]); expect(state.writes).toEqual([]); expect(state.errors).toEqual([])
})
test('parameters survive failed start, and both additional evaluation tabs remain functional',async({page})=>{
  const state=await fixture(page); await open(page)
  await page.getByRole('button',{name:'评测参数',exact:true}).click()
  await page.getByRole('spinbutton',{name:'最近轮次'}).fill('35')
  await page.getByRole('button',{name:'完成',exact:true}).click()
  state.failStart=true
  await page.getByRole('button',{name:'开始评测',exact:true}).click()
  await expect.poll(()=>state.posts.length).toBe(1)
  expect(state.posts[0]).toMatchObject({conversation_id:'conv-a',max_turns:35})
  await expect(page.getByText('评测服务暂不可用',{exact:false}).first()).toBeVisible()
  await page.getByRole('tab',{name:'Golden 评测集',exact:true}).click()
  await expect(page).toHaveURL(/tab=regression/)
  await expect(page.getByText('Golden 评测配置',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'Golden 评测配置',exact:true}).click()
  await expect(page.getByRole('dialog',{name:'Golden 评测参数'})).toBeVisible()
  await page.getByRole('dialog',{name:'Golden 评测参数'}).getByRole('button',{name:'完成',exact:true}).click()
  await page.screenshot({path:`${evidence}/golden.png`})
  await page.getByRole('tab',{name:'检索集健康度',exact:true}).click()
  await expect(page).toHaveURL(/tab=queryset_health/)
  await expect(page.getByText('差异对比',{exact:true})).toBeVisible()
  await page.screenshot({path:`${evidence}/health.png`})
  await page.getByRole('tab',{name:'对话评测',exact:true}).click()
  await page.getByRole('button',{name:'评测参数',exact:true}).click()
  await expect(page.getByRole('spinbutton',{name:'最近轮次'})).toHaveValue('35')
  await page.getByRole('button',{name:'完成',exact:true}).click()
  await page.getByRole('button',{name:/选择对话|工程能力问答/}).first().click()
  await page.getByRole('dialog',{name:'选择对话'}).getByRole('button',{name:/缺少引用的对话/}).click()
  await expect(page.getByRole('button',{name:'开始评测',exact:true})).toBeDisabled()
  await expect(page.getByText('这条对话没有引用上下文',{exact:true})).toBeVisible()
  expect(state.writes).toEqual([])
})
test('narrow screen can read a selected sample and return to matrix without horizontal page overflow',async({page})=>{
  await fixture(page); await page.setViewportSize({width:390,height:844}); await open(page)
  await page.getByRole('table',{name:'逐轮评分矩阵'}).getByRole('button',{name:question,exact:true}).click()
  await expect(page.getByRole('region',{name:'样本阅读区'})).toBeVisible()
  await page.getByRole('button',{name:'返回样本矩阵',exact:true}).click()
  await expect(page.getByRole('table',{name:'逐轮评分矩阵'})).toBeVisible()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1)
  fs.mkdirSync(evidence,{recursive:true}); await page.screenshot({path:`${evidence}/mobile-c.png`})
})
test('light and dark appearance retain the matrix and reader at double pixel density',async({browser})=>{
  const backgrounds: string[]=[]
  for(const mode of ['light','dark'] as const) {
    const context=await browser.newContext({viewport:{width:1600,height:1000},deviceScaleFactor:2,colorScheme:mode})
    try {
      const page=await context.newPage();await fixture(page,{theme:mode});await open(page)
      await expect(page.locator('html')).toHaveClass(new RegExp(mode))
      await page.getByRole('table',{name:'逐轮评分矩阵'}).getByRole('button',{name:question,exact:true}).click()
      await expect(page.locator('[data-evaluation-reader-item="item-5"]')).toHaveCSS('opacity','1')
      backgrounds.push(await page.locator('[data-evaluation-page]').evaluate(element=>getComputedStyle(element).backgroundColor))
      await page.screenshot({path:`${evidence}/${mode}-c-2x.png`})
      expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1)
    } finally { await context.close() }
  }
  expect(backgrounds[0]).not.toBe(backgrounds[1])
})
