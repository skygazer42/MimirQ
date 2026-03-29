import type {
  TenantGroupCreateRequest,
  TenantGroupListResponse,
  TenantGroupMemberListResponse,
  TenantGroupMembersUpdateRequest,
  TenantGroupMembersUpdateResponse,
  TenantGroupOut,
  TenantGroupUpdateRequest,
} from '@/types/backend'

import { apiClient } from '@/lib/api/core'

export interface TenantMember {
  id: string
  tenant_id: string
  user_id?: string | null
  role: string
  is_current: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface TenantMemberListResponse {
  total: number
  items: TenantMember[]
}

export const rbacApi = {
  async listTenantMembers(params: { skip?: number; limit?: number } = {}): Promise<TenantMemberListResponse> {
    const { data } = await apiClient.get('/rbac/members', { params })
    return data
  },

  async patchTenantMemberRole(userId: string, payload: { role: string }): Promise<TenantMember> {
    const { data } = await apiClient.patch(`/rbac/members/${encodeURIComponent(userId)}`, payload)
    return data
  },
}

export const groupApi = {
  async listGroups(params: { skip?: number; limit?: number } = {}): Promise<TenantGroupListResponse> {
    const { data } = await apiClient.get('/groups', { params })
    return data
  },

  async createGroup(payload: TenantGroupCreateRequest): Promise<TenantGroupOut> {
    const { data } = await apiClient.post('/groups', payload)
    return data
  },

  async getGroup(groupId: string): Promise<TenantGroupOut> {
    const { data } = await apiClient.get(`/groups/${encodeURIComponent(groupId)}`)
    return data
  },

  async patchGroup(groupId: string, payload: TenantGroupUpdateRequest): Promise<TenantGroupOut> {
    const { data } = await apiClient.patch(`/groups/${encodeURIComponent(groupId)}`, payload)
    return data
  },

  async deleteGroup(groupId: string): Promise<void> {
    await apiClient.delete(`/groups/${encodeURIComponent(groupId)}`)
  },

  async listGroupMembers(
    groupId: string,
    params: { skip?: number; limit?: number } = {}
  ): Promise<TenantGroupMemberListResponse> {
    const { data } = await apiClient.get(`/groups/${encodeURIComponent(groupId)}/members`, { params })
    return data
  },

  async addGroupMembers(groupId: string, payload: TenantGroupMembersUpdateRequest): Promise<TenantGroupMembersUpdateResponse> {
    const { data } = await apiClient.post(`/groups/${encodeURIComponent(groupId)}/members`, payload)
    return data
  },

  async removeGroupMembers(
    groupId: string,
    payload: TenantGroupMembersUpdateRequest
  ): Promise<TenantGroupMembersUpdateResponse> {
    const { data } = await apiClient.post(`/groups/${encodeURIComponent(groupId)}/members/remove`, payload)
    return data
  },
}
