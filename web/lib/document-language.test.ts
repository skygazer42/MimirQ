import { describe, expect, it } from 'vitest'

import {
  DEFAULT_DOCUMENT_LANGUAGE,
  resolveRequestDocumentLanguage,
  resolveRequestDocumentSettings,
} from './document-language'

describe('document language resolution', () => {
  it('prefers an explicit request override header for deterministic RTL demos', () => {
    const requestHeaders = new Headers({
      'accept-language': 'en-US,en;q=0.9',
      'x-mimirq-lang': 'ar-EG',
    })

    expect(resolveRequestDocumentLanguage(requestHeaders)).toBe('ar-EG')
    expect(resolveRequestDocumentSettings(requestHeaders)).toEqual({
      dir: 'rtl',
      lang: 'ar-EG',
    })
  })

  it('falls back to the first valid Accept-Language candidate', () => {
    const requestHeaders = new Headers({
      'accept-language': '  fa-IR;q=0.9, en-US;q=0.8',
    })

    expect(resolveRequestDocumentLanguage(requestHeaders)).toBe('fa-IR')
  })

  it('ignores invalid request language headers and uses the configured fallback', () => {
    const requestHeaders = {
      get(name: string) {
        if (name === 'accept-language') return '***, ???'
        if (name === 'x-app-lang') return '中文'
        return null
      },
    }

    expect(resolveRequestDocumentLanguage(requestHeaders, 'en-US')).toBe('en-US')
  })

  it('uses the default document language when nothing valid is available', () => {
    expect(resolveRequestDocumentLanguage(undefined, '')).toBe(DEFAULT_DOCUMENT_LANGUAGE)
  })
})
