import { apiClient } from '@/lib/api/core'

function buildScimHeaders(scimToken: string, tenantId: string): Record<string, string> {
  const token = String(scimToken || '').trim()
  const tid = String(tenantId || '').trim()
  if (!token) throw new Error('SCIM token required')
  if (!tid) throw new Error('tenantId required')

  return {
    Authorization: `Bearer ${token}`,
    'X-Tenant-ID': tid,
    'Content-Type': 'application/scim+json',
  }
}

export const scimApi = {
  async getServiceProviderConfig(params: { tenantId: string; scimToken: string }): Promise<any> {
    const { data } = await apiClient.get('/scim/v2/ServiceProviderConfig', {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async listSchemas(params: { tenantId: string; scimToken: string }): Promise<any> {
    const { data } = await apiClient.get('/scim/v2/Schemas', {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async listResourceTypes(params: { tenantId: string; scimToken: string }): Promise<any> {
    const { data } = await apiClient.get('/scim/v2/ResourceTypes', {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async listGroups(params: { tenantId: string; scimToken: string; startIndex?: number; count?: number }): Promise<any> {
    const { tenantId, scimToken, ...query } = params
    const { data } = await apiClient.get('/scim/v2/Groups', {
      headers: buildScimHeaders(scimToken, tenantId),
      params: query,
    })
    return data
  },

  async getGroup(params: { tenantId: string; scimToken: string; groupId: string }): Promise<any> {
    const { data } = await apiClient.get(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async createGroup(params: { tenantId: string; scimToken: string; payload: any }): Promise<any> {
    const { data } = await apiClient.post('/scim/v2/Groups', params.payload, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async updateGroup(params: { tenantId: string; scimToken: string; groupId: string; payload: any }): Promise<any> {
    const { data } = await apiClient.put(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, params.payload, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async deleteGroup(params: { tenantId: string; scimToken: string; groupId: string }): Promise<any> {
    const { data } = await apiClient.delete(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async listUsers(params: { tenantId: string; scimToken: string; startIndex?: number; count?: number }): Promise<any> {
    const { tenantId, scimToken, ...query } = params
    const { data } = await apiClient.get('/scim/v2/Users', {
      headers: buildScimHeaders(scimToken, tenantId),
      params: query,
    })
    return data
  },

  async getUser(params: { tenantId: string; scimToken: string; userId: string }): Promise<any> {
    const { data } = await apiClient.get(`/scim/v2/Users/${encodeURIComponent(params.userId)}`, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async createUser(params: { tenantId: string; scimToken: string; payload: any }): Promise<any> {
    const { data } = await apiClient.post('/scim/v2/Users', params.payload, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async patchUser(params: { tenantId: string; scimToken: string; userId: string; payload: any }): Promise<any> {
    const { data } = await apiClient.patch(`/scim/v2/Users/${encodeURIComponent(params.userId)}`, params.payload, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async patchGroup(params: { tenantId: string; scimToken: string; groupId: string; payload: any }): Promise<any> {
    const { data } = await apiClient.patch(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, params.payload, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },
}
