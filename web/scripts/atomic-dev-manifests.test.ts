import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { afterEach, describe, expect, it, vi } from 'vitest'

const roots: string[] = []
afterEach(() => {
  vi.useRealTimers()
  for (const root of roots.splice(0)) {
    const resolved = fs.realpathSync(root)
    if (!resolved.startsWith(fs.realpathSync(os.tmpdir()) + path.sep + 'ragvia-manifest-')) throw new Error('Unexpected test cleanup path')
    fs.rmSync(resolved, { recursive: true })
  }
})

async function writer(fileSystem: typeof fs) {
  const filename = path.resolve('scripts/atomic-dev-manifests.mjs')
  // Before the adapter exists this runs the existing direct writer as a control.
  if (!fs.existsSync(filename)) return fileSystem
  const manifestModule = await import(/* @vite-ignore */ pathToFileURL(filename).href)
  return manifestModule.createAtomicManifestFileSystem(fileSystem) as typeof fs
}

describe('development manifest publication', () => {
  it('versions only the shared layout and keeps unknown on-demand routes at their original path', async () => {
    const manifestModule = await import(/* @vite-ignore */ pathToFileURL(path.resolve('scripts/atomic-dev-manifests.mjs')).href)
    const original = 'static/chunks/[name].js'
    const filename = manifestModule.versionRootLayoutFilename(original)
    expect(filename({ chunk: { name: 'app/layout' } })).toBe('static/chunks/[name].[contenthash:8].js')
    expect(filename({ chunk: { name: 'app/datasets/[id]/profile/page' } })).toBe(original)
    expect(filename({ chunk: { id: 'new-route-not-compiled-yet' } })).toBe(original)
    const originalFunction = vi.fn(() => original)
    const wrapped = manifestModule.versionRootLayoutFilename(originalFunction)
    const data = { chunk: { name: 'other' } }, info = { immutable: false }
    expect(wrapped(data, info)).toBe(original)
    expect(originalFunction).toHaveBeenCalledWith(data, info)
  })
  it.each(['build-manifest.json', 'page_client-reference-manifest.js', 'layout.js', 'webpack.hot-update.js'])('readers keep the complete previous %s until replacement is complete', async filename => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ragvia-manifest-')); roots.push(root)
    const target = path.join(root, filename), previous = '{"version":1}', next = '{"version":2,"routes":["/datasets","/graph"]}'
    fs.writeFileSync(target, previous)
    let release!: () => void, started!: () => void
    const beginning = new Promise<void>(resolve => { started = resolve })
    const adapter = Object.assign(Object.create(fs), { writeFile: ((file: fs.PathOrFileDescriptor, data: string | Uint8Array, ...args: unknown[]) => {
      const callback = args.at(-1) as (error: NodeJS.ErrnoException | null) => void
      fs.writeFileSync(file, String(data).slice(0, 1))
      release = () => fs.writeFile(file, data, callback)
      started()
    }) as typeof fs.writeFile }) as typeof fs
    const output = await writer(adapter)
    const completed = new Promise<void>((resolve, reject) => output.writeFile(target, next, error => error ? reject(error) : resolve()))
    await beginning
    const duringWrite = fs.readFileSync(target, 'utf8')
    release(); await completed
    expect(duringWrite).toBe(previous)
    expect(JSON.parse(fs.readFileSync(target, 'utf8')).version).toBe(2)
    expect(fs.readdirSync(root)).toEqual([filename])
  })

  it('propagates write errors and keeps the previous manifest', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ragvia-manifest-')); roots.push(root)
    const target = path.join(root, 'build-manifest.json'); fs.writeFileSync(target, '{"version":1}')
    const failure = new Error('disk write failed')
    const adapter = Object.assign(Object.create(fs), { writeFile: ((_file: unknown, _data: unknown, callback: (error: Error) => void) => callback(failure)) as typeof fs.writeFile }) as typeof fs
    const output = await writer(adapter)
    await expect(new Promise((resolve, reject) => output.writeFile(target, '{}', error => error ? reject(error) : resolve(null)))).rejects.toBe(failure)
    expect(JSON.parse(fs.readFileSync(target, 'utf8')).version).toBe(1)
  })

  it('retries a Windows sharing lock while the previous chunk remains readable', async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ragvia-manifest-')); roots.push(root)
    const target = path.join(root, 'layout.js'); fs.writeFileSync(target, '{"version":1}')
    const lock = Object.assign(new Error('sharing violation'), { code: 'EPERM' })
    let attempts = 0
    const adapter = Object.assign(Object.create(fs), { rename: ((source: fs.PathLike, destination: fs.PathLike, callback: (error: NodeJS.ErrnoException | null) => void) => {
      attempts++
      if (attempts === 1) { expect(fs.readFileSync(target, 'utf8')).toBe('{"version":1}'); callback(lock) }
      else fs.rename(source, destination, callback)
    }) as typeof fs.rename }) as typeof fs
    const output = await writer(adapter)
    await new Promise<void>((resolve, reject) => output.writeFile(target, '{"version":2}', error => error ? reject(error) : resolve()))
    expect(attempts).toBe(2)
    expect(JSON.parse(fs.readFileSync(target, 'utf8')).version).toBe(2)
  })

  it('reports a persistent sharing lock instead of emitting success', async () => {
    const lock = Object.assign(new Error('persistent sharing violation'), { code: 'EPERM' })
    const rename = vi.fn((_source: unknown, _target: unknown, callback: (error: Error) => void) => callback(lock))
    const adapter = Object.assign(Object.create(fs), { writeFile: (_file: unknown, _content: unknown, callback: (error: null) => void) => callback(null), rename }) as typeof fs
    const output = await writer(adapter)
    vi.useFakeTimers()
    const assertion = expect(new Promise<void>((resolve, reject) => output.writeFile('layout.js', '{}', error => error ? reject(error) : resolve()))).rejects.toBe(lock)
    await vi.runAllTimersAsync()
    await assertion
    expect(rename.mock.calls.length).toBeGreaterThan(1)
    expect(rename.mock.calls.length).toBeLessThanOrEqual(7)
  })
})
