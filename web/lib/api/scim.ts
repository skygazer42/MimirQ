import { apiClient, type ApiRequestOptions } from '@/lib/api/core'

type ScimPayload = Record<string, unknown>

type ScimCredentials = { tenantId: string; scimToken: string }
type ScimListParams = ScimCredentials & { startIndex?: number; count?: number }

function buildScimHeaders({ scimToken, tenantId }: Readonly<ScimCredentials>): Record<string, string> {
  const token = scimToken.trim()
  const normalizedTenantId = tenantId.trim()
  if (token === '') throw new Error('SCIM token required')
  if (normalizedTenantId === '') throw new Error('tenantId required')

  return {
    Authorization: `Bearer ${token}`,
    'X-Tenant-ID': normalizedTenantId,
    'Content-Type': 'application/scim+json',
  }
}

export const scimApi = {
  async getServiceProviderConfig(params: ScimCredentials, options?: ApiRequestOptions): Promise<unknown> {
    const { data } = await apiClient.get('/scim/v2/ServiceProviderConfig', {
      headers: buildScimHeaders(params),
      signal: options?.signal,
    })
    return data
  },

  async listSchemas(params: ScimCredentials): Promise<unknown> {
    const { data } = await apiClient.get('/scim/v2/Schemas', {
      headers: buildScimHeaders(params),
    })
    return data
  },

  async listResourceTypes(params: ScimCredentials): Promise<unknown> {
    const { data } = await apiClient.get('/scim/v2/ResourceTypes', {
      headers: buildScimHeaders(params),
    })
    return data
  },

  async listGroups(params: ScimListParams): Promise<unknown> {
    const { tenantId, scimToken, ...query } = params
    const { data } = await apiClient.get('/scim/v2/Groups', {
      headers: buildScimHeaders({ scimToken, tenantId }),
      params: query,
    })
    return data
  },

  async getGroup(params: ScimCredentials & { groupId: string }): Promise<unknown> {
    const { data } = await apiClient.get(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, {
      headers: buildScimHeaders(params),
    })
    return data
  },

  async createGroup(params: ScimCredentials & { payload: ScimPayload }): Promise<unknown> {
    const { data } = await apiClient.post('/scim/v2/Groups', params.payload, {
      headers: buildScimHeaders(params),
    })
    return data
  },

  async updateGroup(params: ScimCredentials & { groupId: string; payload: ScimPayload }): Promise<unknown> {
    const { data } = await apiClient.put(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, params.payload, {
      headers: buildScimHeaders(params),
    })
    return data
  },

  async deleteGroup(params: ScimCredentials & { groupId: string }): Promise<unknown> {
    const { data } = await apiClient.delete(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, {
      headers: buildScimHeaders(params),
    })
    return data
  },

  async listUsers(params: ScimListParams): Promise<unknown> {
    const { tenantId, scimToken, ...query } = params
    const { data } = await apiClient.get('/scim/v2/Users', {
      headers: buildScimHeaders({ scimToken, tenantId }),
      params: query,
    })
    return data
  },

  async getUser(params: ScimCredentials & { userId: string }): Promise<unknown> {
    const { data } = await apiClient.get(`/scim/v2/Users/${encodeURIComponent(params.userId)}`, {
      headers: buildScimHeaders(params),
    })
    return data
  },

  async createUser(params: ScimCredentials & { payload: ScimPayload }): Promise<unknown> {
    const { data } = await apiClient.post('/scim/v2/Users', params.payload, {
      headers: buildScimHeaders(params),
    })
    return data
  },

  async patchUser(params: ScimCredentials & { userId: string; payload: ScimPayload }): Promise<unknown> {
    const { data } = await apiClient.patch(`/scim/v2/Users/${encodeURIComponent(params.userId)}`, params.payload, {
      headers: buildScimHeaders(params),
    })
    return data
  },

  async patchGroup(params: ScimCredentials & { groupId: string; payload: ScimPayload }): Promise<unknown> {
    const { data } = await apiClient.patch(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, params.payload, {
      headers: buildScimHeaders(params),
    })
    return data
  },
}
