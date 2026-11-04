import { describe, expect, it } from 'vitest'

import { extractFrontendRoutesFromFile, listFrontendSourceFiles, parseFrontendRoutes } from './api-contract-lib.mjs'

describe('API contract route extraction', () => {
  it('finds API client modules with the paths used by the coverage checker', () => {
    const contractFiles = listFrontendSourceFiles().filter(
      (file) => file === 'web/lib/api-client.ts' || file.startsWith('web/lib/api/'),
    )

    expect(contractFiles).toContain('web/lib/api/chat.ts')
    expect(parseFrontendRoutes({ files: contractFiles })).toContainEqual({
      method: 'POST',
      path: '/chat/stream',
      src: 'web/lib/api/chat.ts',
    })
  })

  it('recognizes routes called through authenticatedFetch', () => {
    expect(extractFrontendRoutesFromFile('web/lib/api/chat.ts')).toContainEqual({
      method: 'POST',
      path: '/chat/stream',
      src: 'web/lib/api/chat.ts',
    })
  })
})
