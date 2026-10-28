import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import ts from 'typescript'
import { test, expect } from '@playwright/test'
import { precheckFixture, precheckRoute } from './precheck-workspace.helpers'

test('locate blank-mount script errors without reloading or hiding them', async ({ browser }) => {
  test.setTimeout(300000)
  const out = path.resolve(__dirname, '../../artifacts/rebrand/remaining-pages-2026-10-27/runtime')
  fs.mkdirSync(out, { recursive: true })
  const all: unknown[] = []
  for (let attempt = 0; attempt < 8; attempt++) {
    const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
    const page = await context.newPage()
    const cdp = await context.newCDPSession(page)
    await cdp.send('Network.enable', { maxTotalBufferSize: 250000000, maxResourceBufferSize: 50000000 })
    await precheckFixture(page, attempt % 2 ? 'dark' : 'light')
    const errors: string[] = [], scriptErrors: unknown[] = [], readErrors: unknown[] = [], requests: Promise<void>[] = []
    page.on('pageerror', error => errors.push(`${error.name}: ${error.message}\n${error.stack ?? ''}`))
    page.on('response', response => {
      if (!response.url().includes('/_next/') || !response.url().split('?')[0].endsWith('.js')) return
      requests.push((async () => {
        const body = await response.text()
        try {
          new vm.Script(body, { filename: response.url() })
          const source = ts.createSourceFile('asset.js', body, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
          function inspect(node: ts.Node) {
            if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'eval') {
              const candidate = node.arguments[0]
              const value = candidate && ts.isStringLiteral(candidate) ? candidate : candidate && ts.isCallExpression(candidate) ? candidate.arguments.find(ts.isStringLiteral) : undefined
              if (value && ts.isStringLiteral(value)) new vm.Script(value.text, { filename: response.url() })
            }
            ts.forEachChild(node, inspect)
          }
          inspect(source)
        }
        catch (error) {
          const filename = `attempt-${attempt}-${scriptErrors.length}.js`
          fs.writeFileSync(path.join(out, filename), body)
          scriptErrors.push({ url: response.url(), status: response.status(), headers: response.headers(), error: String(error), bytes: Buffer.byteLength(body), filename })
        }
      })().catch(error => { readErrors.push({ url: response.url(), readError: String(error) }) }))
    })
    await page.goto(precheckRoute, { waitUntil: 'load' })
    const mounted = await page.getByRole('heading', { name: '文档预检', exact: true }).waitFor({ state: 'visible', timeout: 60000 }).then(() => true, () => false)
    await Promise.all(requests)
    const inline = await page.locator('script:not([src])').allTextContents()
    for (let index = 0; index < inline.length; index++) {
      try { new vm.Script(inline[index]) }
      catch (error) { scriptErrors.push({ inline: index, error: String(error), text: inline[index].slice(0, 500) }) }
    }
    const entry = { attempt, mounted, errors, scriptErrors, readErrors }
    all.push(entry); fs.writeFileSync(path.join(out, 'probe.json'), JSON.stringify(all, null, 2))
    if (!mounted || errors.length || scriptErrors.length) {
      await page.screenshot({ path: path.join(out, `attempt-${attempt}.png`) })
      fs.writeFileSync(path.join(out, `attempt-${attempt}.html`), await page.content())
    }
    await context.close()
    if (scriptErrors.length || errors.length || !mounted) break
  }
  expect(all).not.toEqual([])
})
