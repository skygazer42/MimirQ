import { getAuthHeaders } from './auth-headers'
import { API_BASE_URL } from './env'

type PdfJsModule = typeof import('pdfjs-dist/build/pdf.mjs')

export type PdfSource = File | string

export function getPdfSource(file: File | null | undefined, fileUrl: string | null | undefined): PdfSource | null {
  const source = file ?? fileUrl
  if (source === undefined || source === null || source === '') return null
  return source
}

const PDFJS_MODULE_URL = '/pdfjs/build/pdf.mjs'
const PDFJS_WORKER_URL = '/pdfjs-compat/pdf.worker.mjs'
let pdfJsModulePromise: Promise<PdfJsModule> | null = null

function installPdfJsCompatPolyfills() {
  const promiseCtor = Promise as typeof Promise & {
    withResolvers?: () => {
      promise: Promise<unknown>
      resolve: (value: unknown) => void
      reject: (reason?: unknown) => void
    }
  }

  if (typeof promiseCtor.withResolvers !== 'function') {
    Object.defineProperty(promiseCtor, 'withResolvers', {
      configurable: true,
      writable: true,
      value() {
        let resolve!: (value: unknown) => void
        let reject!: (reason?: unknown) => void
        const promise = new Promise((innerResolve, innerReject) => {
          resolve = innerResolve
          reject = innerReject
        })

        return { promise, resolve, reject }
      },
    })
  }

  const mapPrototype = Map.prototype as typeof Map.prototype & {
    getOrInsertComputed?: (key: unknown, compute: (key: unknown) => unknown) => unknown
  }

  if (typeof mapPrototype.getOrInsertComputed !== 'function') {
    Object.defineProperty(mapPrototype, 'getOrInsertComputed', {
      configurable: true,
      writable: true,
      value(this: Map<unknown, unknown>, key: unknown, compute: (key: unknown) => unknown) {
        if (this.has(key)) {
          return this.get(key)
        }

        const value = compute(key)
        this.set(key, value)
        return value
      },
    })
  }
}

export async function loadPdfJsModule(): Promise<PdfJsModule> {
  if (pdfJsModulePromise === null) {
    installPdfJsCompatPolyfills()
    // The served module matches the installed SDK and stays outside webpack wrapping.
    pdfJsModulePromise = import(/* webpackIgnore: true */ PDFJS_MODULE_URL) as Promise<PdfJsModule>
  }
  const pending = pdfJsModulePromise
  try {
    const pdfjsLib = await pending
    pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER_URL
    return pdfjsLib
  } catch (error) {
    if (pdfJsModulePromise === pending) pdfJsModulePromise = null
    throw error
  }
}

function getPdfSourceHeaders(fileUrl: string): Record<string, string> | undefined {
  const parsedUrl = new URL(fileUrl, window.location.origin)
  if (!parsedUrl.pathname.startsWith('/api/')) return undefined
  const apiUrl = new URL(API_BASE_URL, window.location.origin)
  if (parsedUrl.origin !== apiUrl.origin && parsedUrl.origin !== window.location.origin) return undefined
  return getAuthHeaders()
}

export async function readPdfSourceData(source: PdfSource, signal: AbortSignal): Promise<Uint8Array> {
  signal.throwIfAborted()
  if (typeof source === 'string') {
    const response = await fetch(source, {
      credentials: 'include',
      headers: getPdfSourceHeaders(source),
      signal,
    })
    if (!response.ok) {
      throw new Error(`PDF 下载失败 (${response.status})`)
    }
    return new Uint8Array(await response.arrayBuffer())
  }

  return new Uint8Array(await source.arrayBuffer())
}
