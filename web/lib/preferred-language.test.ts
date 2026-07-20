import { AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'

import { applyPreferredLanguageAxiosHeader, resolveBrowserPreferredLanguage, withPreferredLanguageHeader } from './preferred-language'

describe('preferred language headers', () => {
  it('uses the first valid browser language', () => {
    expect(resolveBrowserPreferredLanguage({ languages: ['not valid', 'zh-CN'], language: 'en-US' })).toBe('zh-CN')
  })

  it('does not overwrite an explicit header', () => {
    expect(withPreferredLanguageHeader({ 'accept-language': 'en-US' }, 'zh-CN')).toEqual({ 'accept-language': 'en-US' })
    const headers = new AxiosHeaders({ 'Accept-Language': 'en-US' })
    applyPreferredLanguageAxiosHeader(headers, 'zh-CN')
    expect(headers.get('Accept-Language')).toBe('en-US')
  })
})
