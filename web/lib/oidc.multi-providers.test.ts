import { describe, expect, it } from 'vitest'

import { isOidcEnabled } from './oidc'

describe('OIDC multi-provider env', () => {
  it('enables OIDC when NEXT_PUBLIC_OIDC_PROVIDERS_JSON is configured', () => {
    const saved = { ...process.env }
    try {
      delete process.env.NEXT_PUBLIC_OIDC_ISSUER
      delete process.env.NEXT_PUBLIC_OIDC_CLIENT_ID
      delete process.env.NEXT_PUBLIC_OIDC_ENABLED

      process.env.NEXT_PUBLIC_OIDC_PROVIDERS_JSON = JSON.stringify([
        {
          id: 'okta',
          name: 'Okta',
          issuer: 'https://idp.example/okta',
          client_id: 'client-okta',
        },
        {
          id: 'google',
          name: 'Google',
          issuer: 'https://accounts.google.com',
          client_id: 'client-google',
        },
      ])

      expect(isOidcEnabled()).toBe(true)
    } finally {
      process.env = saved
    }
  })
})

