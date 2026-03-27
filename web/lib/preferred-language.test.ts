import { AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'

import {
  applyPreferredLanguageAxiosHeader,
  resolveBrowserPreferredLanguage,
  withPreferredLanguageHeader,
} from './preferred-language'

describe('preferred language resolution', () => {
  it('returns the first valid browser language', () => {
    expect(
      resolveBrowserPreferredLanguage({
        languages: ['  zh-CN  ', 'en-US'],
        language: 'en-US',
      })
    ).toBe('zh-CN')
  })

  it('falls back to navigator.language when languages are unavailable', () => {
    expect(
      resolveBrowserPreferredLanguage({
        language: 'fr-CA',
      })
    ).toBe('fr-CA')
  })

  it('returns undefined when language tags are invalid', () => {
    expect(
      resolveBrowserPreferredLanguage({
        languages: ['中文', '', '###'],
        language: '***',
      })
    ).toBeUndefined()
  })
})

describe('preferred language header injection', () => {
  it('adds Accept-Language header for plain request header objects', () => {
    const headers = withPreferredLanguageHeader(
      {
        Accept: 'text/event-stream',
      },
      'ja-JP'
    )
    expect(headers['Accept-Language']).toBe('ja-JP')
  })

  it('does not override an explicitly provided Accept-Language header', () => {
    const headers = withPreferredLanguageHeader(
      {
        'accept-language': 'de-DE',
      },
      'ja-JP'
    )
    expect(headers['accept-language']).toBe('de-DE')
    expect(headers['Accept-Language']).toBeUndefined()
  })

  it('does not override an existing axios Accept-Language header', () => {
    const headers = AxiosHeaders.from({
      'accept-language': 'es-ES',
    })
    applyPreferredLanguageAxiosHeader(headers, 'it-IT')
    expect(headers.get('Accept-Language')).toBe('es-ES')
  })
})
