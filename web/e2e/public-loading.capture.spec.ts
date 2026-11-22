import path from 'node:path'
import { NextIntlClientProvider } from 'next-intl'
import { createElement, type ComponentType } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { jsx } from 'react/jsx-runtime'
import { test, expect } from '@playwright/test'
import commonMessages from '../i18n/messages/zh-CN/common'
import { openPublicState, publicStateFixture, publicStateShot } from './public-states.helpers'

const loadings = {
  root: '/app/loading.tsx',
  dataset: '/app/datasets/loading.tsx',
  knowledge: '/app/knowledge/loading.tsx',
  evaluation: '/app/evaluation/loading.tsx',
  graph: '/app/graph/loading.tsx',
  settings: '/app/settings/loading.tsx',
}

async function renderLoadings() {
  const { createServer } = await import('vite')
  const root = path.resolve(__dirname, '..')
  const imageModule = 'virtual:next-image'
  const vite = await createServer({
    configFile: false,
    root,
    publicDir: false,
    optimizeDeps: { noDiscovery: true, include: [] },
    resolve: { alias: { '@': root, 'next/image': imageModule } },
    server: { middlewareMode: true, hmr: false, watch: null },
    plugins: [
      {
        name: 'next-image-interop',
        resolveId(id) {
          if (id === imageModule) return id
        },
        load(id) {
          // Next exposes its image component through a CommonJS default export.
          if (id === imageModule) return "import image from 'next/image.js'; export default image.default;"
        },
      },
    ],
  })
  try {
    return await Promise.all(
      Object.entries(loadings).map(async ([name, file]) => {
        const { default: Loading } = (await vite.ssrLoadModule(file)) as { default: ComponentType }
        const body = renderToStaticMarkup(
          jsx(NextIntlClientProvider, {
            locale: 'zh-CN',
            messages: commonMessages,
            timeZone: 'UTC',
            children: createElement(Loading),
          }),
        )
        return [name, body] as const
      }),
    )
  } finally {
    await vite.close()
  }
}

test('capture actual loading component outputs in desktop and phone layouts', async ({ page }) => {
  await publicStateFixture(page)
  await openPublicState(page, '/settings/rbac', '无权限访问')
  const css = await page
    .locator('link[rel="stylesheet"]')
    .evaluateAll((links) => links.map((link) => (link as HTMLLinkElement).href))
  const inline = await page.locator('html').getAttribute('style')
  const stylesheets = css.map((href) => `<link rel="stylesheet" href="${href}">`).join('')
  for (const [name, body] of await renderLoadings()) {
    const html = `<!doctype html><html lang="zh-CN" data-surface-theme="ocean" style="${inline ?? ''}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">${stylesheets}</head><body class="font-sans">${body}</body></html>`
    await page.route(`**/__boundary-evidence__/loading-${name}.html`, (route) =>
      route.fulfill({ contentType: 'text/html', body: html }),
    )
  }
  for (const size of [
    { width: 1600, height: 1000, name: 'desktop' },
    { width: 390, height: 844, name: 'phone' },
  ]) {
    await page.setViewportSize(size)
    for (const name of Object.keys(loadings)) {
      await page.goto(`/__boundary-evidence__/loading-${name}.html`, { waitUntil: 'load' })
      await expect(page.getByRole('status')).toBeVisible()
      await publicStateShot(page, `after-loading-${name}-${size.name}`)
    }
  }
})
