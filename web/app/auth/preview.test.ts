// @vitest-environment happy-dom

import fs from 'node:fs'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

describe('auth design preview handoff', () => {
  afterEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  it('explains a valid preview submission and links to real registration without sending credentials', () => {
    const html = fs.readFileSync(path.resolve(__dirname, '../../public/brand/explorations/ragvia/login.html'), 'utf8')
    const body = html.match(/<body>([\s\S]*?)<script>/)?.[1]
    const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1]
    expect(body).toBeDefined()
    expect(script).toBeDefined()
    document.body.innerHTML = body!
    const fetchSpy = vi.spyOn(window, 'fetch')
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem')
    // Execute the repository's authored preview script against its actual form.
    new Function(script!)()
    document.querySelector<HTMLButtonElement>('#mode-switch')!.click()
    for (const [id, value] of Object.entries({
      email: 'reader@example.com', username: 'reader',
      password: 'valid-reader-password', 'confirm-password': 'valid-reader-password',
    })) {
      document.querySelector<HTMLInputElement>(`#${id}`)!.value = value
    }

    document.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))

    const status = document.querySelector<HTMLElement>('#preview-status')
    expect(status?.hidden).toBe(false)
    expect(status?.textContent).toContain('设计预览')
    expect(status?.querySelector('a')?.getAttribute('href')).toBe('/auth?mode=register')
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(storageSpy).not.toHaveBeenCalled()
  })
})
