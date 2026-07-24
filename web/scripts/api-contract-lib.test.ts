import { describe, expect, it } from 'vitest'

import { extractFrontendRoutesFromFile } from './api-contract-lib.mjs'


describe('API contract route extraction', () => {
  it('recognizes routes called through authenticatedFetch', () => {
    expect(extractFrontendRoutesFromFile('web/lib/api/chat.ts')).toContainEqual({
      method: 'POST',
      path: '/chat/stream',
      src: 'web/lib/api/chat.ts',
    })
  })
})
