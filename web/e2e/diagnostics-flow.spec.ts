import fs from 'node:fs'
import { expect,test } from '@playwright/test'
import { diagnosticFixture,evidence,openDiagnostics } from './diagnostics-flow.helpers'

async function runPreview(page:import('@playwright/test').Page,question='服务升级失败后如何回滚？') {
  await page.getByRole('textbox',{name:'诊断问题',exact:true}).fill(question)
  await page.getByRole('button',{name:'运行预览',exact:true}).click()
  await expect(page.getByRole('button',{name:/引用输出/})).toContainText('6')
}

test('A starts with an honest pending workspace and keeps optional services neutral',async({page})=>{
  const state=await diagnosticFixture(page);await openDiagnostics(page)
  fs.mkdirSync(evidence,{recursive:true});await page.screenshot({path:`${evidence}/pending.png`})
  await expect(page.getByRole('region',{name:'检索链路',exact:true})).toBeVisible({timeout:8000})
  await expect(page.getByRole('region',{name:'检索链路',exact:true})).toContainText('待执行')
  await expect(page.getByRole('button',{name:'运行预览',exact:true})).toBeDisabled()
  const redis=page.getByRole('region',{name:'服务依赖'}).locator('div').filter({hasText:/^Redis未启用$/})
  await expect(redis).toBeVisible()
  expect(state.requests).toEqual([]);expect(state.errors).toEqual([])
})

test('preview renders returned channels and units, keeps quality unknown and exposes raw evidence',async({page})=>{
  const state=await diagnosticFixture(page);await openDiagnostics(page)
  await page.getByRole('button',{name:'诊断文档范围',exact:true}).click()
  await page.getByRole('checkbox',{name:'服务发布规范.pdf',exact:true}).check()
  await page.keyboard.press('Escape')
  await runPreview(page)
  const chain=page.getByRole('region',{name:'检索链路',exact:true})
  await expect(chain.getByRole('button',{name:/向量召回/})).toContainText('32')
  await expect(chain.getByRole('button',{name:/图谱召回/})).toContainText('3')
  await expect(chain.getByRole('button',{name:/引用输出/})).toContainText('6')
  await expect(page.getByRole('region',{name:'质量读数'})).toContainText('未返回')
  await expect(page.getByText('1,248',{exact:true})).toBeVisible();await expect(page.getByText(/^286\s*ms$/)).toBeVisible()
  expect(state.requests.find(r=>r.path.endsWith('/prompt-preview'))?.body).toMatchObject({dataset_id:'dataset-a',document_ids:['doc-a'],query:'服务升级失败后如何回滚？',structured_output:false})
  await page.screenshot({path:`${evidence}/desktop-returned.png`})
  await chain.getByRole('button',{name:/引用输出/}).click()
  const dialog=page.getByRole('dialog',{name:'引用输出',exact:true})
  await expect(dialog.getByRole('heading',{name:'服务发布规范.pdf',exact:true}).first()).toBeVisible()
  await expect(dialog.getByRole('heading',{name:'回滚清单.md',exact:true}).first()).toBeVisible()
  await dialog.getByText('原始引用字段',{exact:true}).click()
  await expect(dialog.locator('pre')).toContainText('回滚检查 1')
  await page.keyboard.press('Escape')
  await page.getByRole('button',{name:'查看原始响应',exact:true}).click()
  const raw=page.getByRole('dialog',{name:'原始响应',exact:true})
  await expect(raw.locator('pre')).toContainText('"document_ids": [')
  await raw.getByRole('button',{name:'关闭',exact:true}).click()
  await expect(page.getByRole('button',{name:'查看原始响应',exact:true})).toBeFocused()
  expect(state.errors).toEqual([]);expect(state.consoleErrors).toEqual([])
})

test('failed preview keeps the question and retry locks duplicate submissions',async({page})=>{
  const state=await diagnosticFixture(page);state.failPreview=true;await openDiagnostics(page)
  const input=page.getByRole('textbox',{name:'诊断问题',exact:true})
  await input.fill('验证失败重试');await page.getByRole('button',{name:'运行预览',exact:true}).click()
  await expect(page.getByRole('region',{name:'检索链路'}).getByRole('alert')).toContainText('检索服务暂不可用')
  await expect(input).toHaveValue('验证失败重试')
  state.failPreview=false;let release=()=>{};state.previewGate=new Promise<void>(resolve=>{release=resolve})
  try {
    await page.getByRole('button',{name:'运行预览',exact:true}).click()
    await expect(page.getByRole('button',{name:'预览中',exact:true})).toBeDisabled()
    await expect(input).toBeDisabled()
    await expect.poll(()=>state.requests.filter(r=>r.path.endsWith('/prompt-preview')).length).toBe(2)
  } finally {release();state.previewGate=null}
  await expect(page.getByRole('region',{name:'检索链路'})).toContainText('已返回')
  await expect(input).toHaveValue('验证失败重试')
  expect(state.errors).toEqual([])
})

test('explain failure preserves the successful preview and changing datasets resets only scoped evidence',async({page})=>{
  const state=await diagnosticFixture(page);state.failExplain=true;await openDiagnostics(page);await runPreview(page)
  await expect(page.getByRole('region',{name:'检索链路'})).toContainText('部分信息未取得')
  await expect(page.getByRole('button',{name:/引用输出/})).toContainText('6')
  await page.getByRole('combobox',{name:'诊断数据集',exact:true}).click();await page.getByRole('option',{name:'运维资料',exact:true}).click()
  await expect(page.getByRole('region',{name:'检索链路'})).toContainText('待执行')
  expect(state.requests.filter(r=>r.path.endsWith('/prompt-preview'))).toHaveLength(1)
  await expect(page.getByRole('textbox',{name:'诊断问题',exact:true})).toHaveValue('服务升级失败后如何回滚？')
  await page.getByRole('button',{name:'运行预览',exact:true}).click()
  await expect(page.getByRole('region',{name:'检索链路'})).toContainText('数据集未配置检索参数')
  expect(state.requests.filter(r=>r.path.endsWith('/explain'))).toHaveLength(1)
  expect(state.requests.filter(r=>r.path.endsWith('/config-hash'))).toHaveLength(1)
  expect(state.errors).toEqual([])
})

test('drift validates bounded inputs and keeps no-comparison samples distinct from a clean result',async({page})=>{
  const state=await diagnosticFixture(page);await openDiagnostics(page)
  await page.getByRole('tab',{name:/^向量漂移/}).click()
  await page.getByRole('spinbutton',{name:'采样数量',exact:true}).fill('0')
  await page.getByRole('button',{name:'运行漂移检查',exact:true}).click()
  await expect(page.getByRole('region',{name:'向量漂移检查'}).getByRole('alert')).toContainText('1–2,000')
  expect(state.requests).toEqual([])
  await page.getByRole('spinbutton',{name:'采样数量',exact:true}).fill('200')
  await page.getByRole('button',{name:'运行漂移检查',exact:true}).click()
  await expect(page.getByRole('region',{name:'向量漂移检查'})).toContainText('12%')
  const request=state.requests.find(r=>r.path.endsWith('/embedding-drift/snapshot'))!
  expect(new URLSearchParams(request.params).get('dataset_id')).toBe('dataset-a')
  expect(new URLSearchParams(request.params).get('sample_n')).toBe('200')
  await page.screenshot({path:`${evidence}/drift.png`})
  state.driftOverride={ok:true,drift:{count:0,avg:null},above_threshold:{count:0,ratio:0}}
  await page.getByRole('button',{name:'运行漂移检查',exact:true}).click()
  await expect(page.getByRole('region',{name:'向量漂移检查'})).toContainText('无可比样本')
  await expect(page.getByRole('region',{name:'向量漂移检查'})).toContainText('未评估')
  expect(state.errors).toEqual([])
})

test('performance reads the backend strict gate and remains separate from retrieval scope',async({page})=>{
  const state=await diagnosticFixture(page);await openDiagnostics(page);await runPreview(page)
  await page.getByRole('tab',{name:/^性能门禁/}).click()
  await expect(page.getByText('全局 API',{exact:true})).toBeVisible()
  await page.getByRole('button',{name:'运行性能门禁',exact:true}).click()
  await expect(page.getByRole('region',{name:'性能门禁检查'})).toContainText('未通过')
  const table=page.getByRole('table',{name:'性能门禁分项结果'})
  await expect(table).toContainText('90');await expect(table).toContainText('退化')
  await page.screenshot({path:`${evidence}/performance.png`})
  expect(state.requests.find(r=>r.path.endsWith('/perf-suite/run'))?.body).toEqual({iterations:10,timeout_sec:2})
  await page.getByRole('tab',{name:'检索预览',exact:true}).click()
  await expect(page.getByRole('button',{name:/引用输出/})).toContainText('6')
  expect(state.errors).toEqual([])
})

test('phone dark layout keeps chain, source dialogs and performance identity reachable',async({page})=>{
  const state=await diagnosticFixture(page,'dark');await page.setViewportSize({width:390,height:844});await openDiagnostics(page);await runPreview(page)
  expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1)
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.screenshot({path:`${evidence}/phone-dark.png`})
  await page.getByRole('button',{name:'查看原始响应',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'原始响应',exact:true})
  await expect(dialog.getByRole('button',{name:'关闭',exact:true})).toBeVisible()
  await dialog.getByRole('button',{name:'关闭',exact:true}).click()
  await page.getByRole('tab',{name:/^性能门禁/}).click();await page.getByRole('button',{name:'运行性能门禁',exact:true}).click()
  const table=page.getByRole('table',{name:'性能门禁分项结果'}),wrap=table.locator('..')
  await wrap.evaluate(el=>{el.scrollLeft=el.scrollWidth})
  const box=await table.locator('tbody th').first().boundingBox(),area=await wrap.boundingBox()
  expect(box!.x).toBeGreaterThanOrEqual(area!.x-1);expect(box!.x).toBeLessThanOrEqual(area!.x+2)
  const qps=await table.getByRole('columnheader',{name:'QPS',exact:true}).boundingBox()
  expect(qps!.x).toBeGreaterThanOrEqual(box!.x+box!.width-1)
  expect(qps!.x+qps!.width).toBeLessThanOrEqual(area!.x+area!.width+1)
  await page.screenshot({path:`${evidence}/phone-performance.png`})
  expect(state.errors).toEqual([])
})

test('known memory backend explains unsupported drift without issuing a probe',async({page})=>{
  const state=await diagnosticFixture(page);state.backend='memory';await openDiagnostics(page)
  await page.getByRole('tab',{name:/^向量漂移/}).click()
  await expect(page.getByRole('region',{name:'向量漂移检查'})).toContainText('memory 后端不支持')
  await expect(page.getByRole('button',{name:'运行漂移检查',exact:true})).toBeDisabled()
  expect(state.requests).toEqual([])
})

test('display choices only change readings and preserve the completed query across probes',async({page})=>{
  const state=await diagnosticFixture(page);await openDiagnostics(page);await runPreview(page)
  const table=page.getByRole('table',{name:'诊断评分读数'})
  await expect(table.getByRole('rowheader',{name:'检索相关性',exact:true})).toBeVisible()
  await page.getByRole('checkbox',{name:'检索相关性',exact:true}).uncheck()
  await expect(table.getByRole('rowheader',{name:'检索相关性',exact:true})).toHaveCount(0)
  await page.getByRole('checkbox',{name:'提示词 token',exact:true}).uncheck()
  await expect(page.getByText('1,248',{exact:true})).toHaveCount(0)
  expect(state.requests.filter(r=>r.path.endsWith('/prompt-preview'))).toHaveLength(1)
  await page.getByRole('tab',{name:/^性能门禁/}).click()
  await page.getByRole('tab',{name:'检索预览',exact:true}).click()
  await expect(page.getByRole('textbox',{name:'诊断问题',exact:true})).toHaveValue('服务升级失败后如何回滚？')
  await expect(page.getByRole('checkbox',{name:'提示词 token',exact:true})).not.toBeChecked()
  await expect(page.getByRole('button',{name:/引用输出/})).toContainText('6')
  await page.getByRole('checkbox',{name:'提示词 token',exact:true}).check()
  await expect(page.getByText('1,248',{exact:true})).toBeVisible()
  expect(state.errors).toEqual([])
})

test('phone preview brings returned evidence into view and offers a way back to the query',async({page})=>{
  const state=await diagnosticFixture(page);await page.setViewportSize({width:390,height:844});await openDiagnostics(page)
  const input=page.getByRole('textbox',{name:'诊断问题',exact:true})
  await input.fill('手机查询');await input.press('Enter')
  const heading=page.getByRole('heading',{name:'预览结果',exact:true})
  await expect(heading).toBeFocused()
  await expect(heading).toBeInViewport()
  await expect.poll(async()=>{
    const panel=await page.getByRole('tabpanel',{name:'检索预览',exact:true}).boundingBox()
    const title=await heading.boundingBox()
    return title!.y-panel!.y
  }).toBeLessThan(56)
  await page.getByRole('button',{name:'修改查询',exact:true}).click()
  await expect(input).toBeFocused();await expect(input).toHaveValue('手机查询')
  await expect(input).toBeInViewport()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1)
  expect(state.requests.filter(r=>r.path.endsWith('/prompt-preview'))).toHaveLength(1)
  expect(state.errors).toEqual([])
})

test('appearance and narrow reading preserve controls without page overflow',async({browser})=>{
  fs.mkdirSync(evidence,{recursive:true})
  for(const view of [
    {name:'desktop-dark',width:1600,height:1000,scale:1,theme:'dark' as const},
    {name:'zoom-equivalent',width:800,height:500,scale:2,theme:'light' as const},
    {name:'phone-light-320',width:320,height:844,scale:1,theme:'light' as const},
  ]){
    const context=await browser.newContext({viewport:{width:view.width,height:view.height},deviceScaleFactor:view.scale})
    try{
      const page=await context.newPage(),state=await diagnosticFixture(page,view.theme)
      await page.setViewportSize({width:view.width,height:view.height});await openDiagnostics(page);await runPreview(page)
      await expect(page.getByRole('button',{name:'查看原始响应',exact:true})).toBeInViewport()
      expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1)
      await page.screenshot({path:`${evidence}/${view.name}.png`})
      expect(state.errors).toEqual([])
    }finally{await context.close()}
  }
})
