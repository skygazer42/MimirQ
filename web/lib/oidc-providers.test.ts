import { describe, expect, it } from 'vitest'

import { getOidcPublicProvidersFromEnv, resolveOidcPublicProvider, resolveOidcServerProvider } from './oidc-providers'

describe('oidc-providers', () => {
  it('parses NEXT_PUBLIC_OIDC_PROVIDERS_JSON and requires provider_id when multiple', () => {
    const saved = { ...process.env }
    try {
      delete process.env.NEXT_PUBLIC_OIDC_ISSUER
      delete process.env.NEXT_PUBLIC_OIDC_CLIENT_ID
      delete process.env.NEXT_PUBLIC_OIDC_PROVIDERS

      process.env.NEXT_PUBLIC_OIDC_PROVIDERS_JSON = JSON.stringify([
        { id: 'okta', name: 'Okta', issuer: 'https://idp.example/okta', client_id: 'client-okta' },
        { id: 'google', name: 'Google', issuer: 'https://accounts.google.com', client_id: 'client-google' },
      ])

      const providers = getOidcPublicProvidersFromEnv()
      expect(providers.map((p) => p.id)).toEqual(['okta', 'google'])
      expect(resolveOidcPublicProvider()).toBe(null)
      expect(resolveOidcPublicProvider('okta')?.issuer).toBe('https://idp.example/okta')
    } finally {
      process.env = saved
    }
  })

  it('falls back to single-provider env vars (public + server)', () => {
    const saved = { ...process.env }
    try {
      delete process.env.NEXT_PUBLIC_OIDC_PROVIDERS_JSON
      delete process.env.NEXT_PUBLIC_OIDC_PROVIDERS
      delete process.env.OIDC_PROVIDERS_JSON
      delete process.env.OIDC_PROVIDERS

      process.env.NEXT_PUBLIC_OIDC_ISSUER = 'https://idp.example/'
      process.env.NEXT_PUBLIC_OIDC_CLIENT_ID = 'public-client'

      const publicProviders = getOidcPublicProvidersFromEnv()
      expect(publicProviders).toHaveLength(1)
      expect(publicProviders[0].id).toBe('default')
      expect(publicProviders[0].issuer).toBe('https://idp.example')

      process.env.OIDC_ISSUER = 'https://idp.example/'
      process.env.OIDC_CLIENT_ID = 'server-client'
      process.env.OIDC_CLIENT_SECRET = 'secret'
      process.env.OIDC_CLIENT_AUTH_METHOD = 'post'

      const serverProvider = resolveOidcServerProvider()
      expect(serverProvider?.id).toBe('default')
      expect(serverProvider?.issuer).toBe('https://idp.example')
      expect(serverProvider?.client_id).toBe('server-client')
      expect(serverProvider?.client_secret).toBe('secret')
      expect(serverProvider?.client_auth_method).toBe('post')
    } finally {
      process.env = saved
    }
  })
})

