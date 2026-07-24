import type { AuthResponse, LoginRequest, RegisterRequest, UserProfile } from '@/types'

import { apiClient, openapiRequest } from '@/lib/api/core'

export type RegisterPayload = RegisterRequest & {
  bootstrapToken?: string
}

export const authApi = {
  async register(payload: RegisterPayload): Promise<AuthResponse> {
    const { bootstrapToken, ...body } = payload
    return openapiRequest({
      path: '/api/v1/auth/register',
      method: 'post',
      body,
      headers: bootstrapToken?.trim()
        ? { 'X-Bootstrap-Token': bootstrapToken.trim() }
        : undefined,
    })
  },

  async login(payload: LoginRequest): Promise<AuthResponse> {
    return openapiRequest({ path: '/api/v1/auth/login', method: 'post', body: payload })
  },

  async me(): Promise<UserProfile> {
    return openapiRequest({ path: '/api/v1/auth/me', method: 'get' })
  },

  async samlMetadata(params?: { provider_id?: string | null }): Promise<string> {
    const { data } = await apiClient.get('/auth/saml/metadata', { params, responseType: 'text' })
    return String(data ?? '')
  },

  async samlExchange(body: {
    provider_id?: string | null
    saml_response: string
    relay_state?: string | null
    acs_url?: string | null
  }) {
    const { data } = await apiClient.post('/auth/saml/exchange', body)
    return data
  },
}
