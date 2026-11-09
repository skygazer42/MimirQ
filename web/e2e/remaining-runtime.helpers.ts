import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import vm from 'node:vm'
import ts from 'typescript'
import type { Page } from '@playwright/test'

const runtime = new WeakMap<Page, { errors: string[]; reads: Promise<void>[]; assets: Map<string, string>; readErrors: string[] }>()
export async function installRemainingRuntimeDiagnostics(page: Page) {
  const state = { errors: [] as string[], reads: [] as Promise<void>[], assets: new Map<string, string>(), readErrors: [] as string[] }
  runtime.set(page, state)
  const cdp = await page.context().newCDPSession(page)
  await cdp.send('Network.enable', { maxTotalBufferSize: 250000000, maxResourceBufferSize: 50000000 })
  page.on('pageerror', error => state.errors.push(`${error.name}: ${error.message}\n${error.stack ?? ''}`))
  page.on('response', response => {
    if (!response.url().includes('/_next/') || !response.url().split('?')[0].endsWith('.js')) return
    state.reads.push(response.text().then(body => { state.assets.set(response.url(), body) }, error => { state.readErrors.push(`${response.url()}: ${String(error)}`) }))
  })
}
export async function saveRemainingRuntimeFailure(page: Page, out: string) {
  const state = runtime.get(page)
  if (!state) return
  await Promise.all(state.reads)
  const root = path.join(out, 'runtime', `failure-${Date.now()}`); fs.mkdirSync(root, { recursive: true })
  const assets: unknown[] = []
  for (const [url, body] of state.assets) {
    let failure: string | null = null
    try {
      new vm.Script(body, { filename: url })
      const source = ts.createSourceFile('asset.js', body, ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
      function inspect(node: ts.Node) {
        if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'eval') {
          const arg = node.arguments[0]
          const text = arg && ts.isStringLiteral(arg) ? arg : arg && ts.isCallExpression(arg) ? arg.arguments.find(ts.isStringLiteral) : undefined
          if (text && ts.isStringLiteral(text)) new vm.Script(text.text, { filename: url })
        }
        ts.forEachChild(node, inspect)
      }
      inspect(source)
    } catch (error) { failure = String(error) }
    const filename = crypto.createHash('sha256').update(url).digest('hex').slice(0, 16) + '.js'
    fs.writeFileSync(path.join(root, filename), body)
    assets.push({ url, bytes: Buffer.byteLength(body), sha256: crypto.createHash('sha256').update(body).digest('hex'), failure, filename })
  }
  fs.writeFileSync(path.join(root, 'report.json'), JSON.stringify({ url: page.url(), errors: state.errors, readErrors: state.readErrors, assets }, null, 2))
  fs.writeFileSync(path.join(root, 'page.html'), await page.content())
}
