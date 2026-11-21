import type {
  AuthPolicy,
  AuthResponse,
  LoginRequest,
  OpenApiSchema,
  RegisterRequest,
  UserProfile,
} from '@/types/backend'
import type { OpenApiQueryParams } from '@/types/openapi-helpers'

import { apiClient, openapiRequest, type ApiRequestOptions } from '@/lib/api/core'

type RegisterPayload = RegisterRequest & {
  bootstrapToken?: string
}

type SamlMetadataParams = NonNullable<OpenApiQueryParams<'/api/v1/auth/saml/metadata', 'get'>>
type SamlExchangePayload = Pick<
  OpenApiSchema<'SamlExchangeRequest'>,
  'provider_id' | 'saml_response' | 'relay_state' | 'acs_url'
>
type SamlExchangeResponse = OpenApiSchema<'SamlExchangeResponse'>

export const authApi = {
  async policy(): Promise<AuthPolicy> {
    return openapiRequest({ path: '/api/v1/auth/policy', method: 'get' })
  },

  async signup(payload: RegisterRequest): Promise<AuthResponse> {
    return openapiRequest({ path: '/api/v1/auth/signup', method: 'post', body: payload })
  },

  async register(payload: RegisterPayload): Promise<AuthResponse> {
    const { bootstrapToken, ...body } = payload
    const token = bootstrapToken?.trim()
    return openapiRequest({
      path: '/api/v1/auth/register',
      method: 'post',
      body,
      headers: token === undefined || token === '' ? undefined : { 'X-Bootstrap-Token': token },
    })
  },

  async login(payload: LoginRequest): Promise<AuthResponse> {
    const { data } = await apiClient.post<AuthResponse>('/auth/login', payload, {
      headers: { Authorization: false },
    })
    return data
  },

  async me(options?: ApiRequestOptions): Promise<UserProfile> {
    return openapiRequest({ path: '/api/v1/auth/me', method: 'get', signal: options?.signal })
  },

  async samlMetadata(params?: SamlMetadataParams, options?: ApiRequestOptions): Promise<string> {
    const { data, headers } = await apiClient.get<string>('/auth/saml/metadata', {
      params,
      responseType: 'text',
      signal: options?.signal,
    })
    const contentType = headers['content-type']
    if (typeof contentType !== 'string' || !/^application\/(?:samlmetadata\+xml|xml)(?:\s*;|$)/i.test(contentType)) {
      throw new Error('SAML 元数据响应格式不是 XML')
    }
    return data
  },

  async samlExchange(body: SamlExchangePayload): Promise<SamlExchangeResponse> {
    const { data } = await apiClient.post<SamlExchangeResponse>('/auth/saml/exchange', body, {
      headers: { Authorization: false },
    })
    return data
  },
}
