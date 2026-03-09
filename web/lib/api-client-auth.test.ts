import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient, authApi } from './api-client'

describe('authApi', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('posts the SAML exchange payload to the auth endpoint', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        user: { id: 'u1' },
        token: { access_token: 'token', token_type: 'bearer', expires_in: 3600 },
        return_to: '/',
      },
    } as any)

    const result = await authApi.samlExchange({
      provider_id: 'okta',
      saml_response: 'base64-response',
      relay_state: 'relay',
      acs_url: 'https://app.example.com/api/saml/acs',
    })

    expect(post).toHaveBeenCalledWith('/auth/saml/exchange', {
      provider_id: 'okta',
      saml_response: 'base64-response',
      relay_state: 'relay',
      acs_url: 'https://app.example.com/api/saml/acs',
    })
    expect(result).toEqual({
      user: { id: 'u1' },
      token: { access_token: 'token', token_type: 'bearer', expires_in: 3600 },
      return_to: '/',
    })
  })
})
