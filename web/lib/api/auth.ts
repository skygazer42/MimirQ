import type { AuthResponse, LoginRequest, OpenApiSchema, RegisterRequest, UserProfile } from '@/types/backend'
import type { paths } from '@/types/openapi'

import { apiClient, openapiRequest } from '@/lib/api/core'

export type RegisterPayload = RegisterRequest & {
  bootstrapToken?: string
}

type SamlMetadataParams = NonNullable<paths['/api/v1/auth/saml/metadata']['get']['parameters']['query']>
type SamlExchangePayload = Pick<
  OpenApiSchema<'SamlExchangeRequest'>,
  'provider_id' | 'saml_response' | 'relay_state' | 'acs_url'
>
type SamlExchangeResponse = OpenApiSchema<'SamlExchangeResponse'>

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

  async samlMetadata(params?: SamlMetadataParams): Promise<string> {
    const { data } = await apiClient.get('/auth/saml/metadata', { params, responseType: 'text' })
    return String(data ?? '')
  },

  async samlExchange(body: SamlExchangePayload): Promise<SamlExchangeResponse> {
    const { data } = await apiClient.post('/auth/saml/exchange', body)
    return data
  },
}
