import { z } from 'zod'

import type {
  OpenApiSchema,
  TenantGroupCreateRequest,
  TenantGroupListResponse,
  TenantGroupMemberListResponse,
  TenantGroupMembersUpdateRequest,
  TenantGroupMembersUpdateResponse,
  TenantGroupOut,
  TenantGroupUpdateRequest,
  TenantMemberUpdateRequest,
} from '@/types/backend'
import type { paths } from '@/types/openapi'

import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import { readDirectoryPages } from '@/lib/directory-pagination'
import { parseApiResponse } from '@/lib/openapi-request'
import { matchesResourceId } from '@/lib/resource-id'
import { dateTimeSchema, integerSchema } from '@/lib/response-schema'
import type { TenantAccess } from '@/lib/tenant-permissions'

export type TenantMember = OpenApiSchema<'TenantMemberOut'>
type TenantMemberDeleteResponse = OpenApiSchema<'TenantMemberDeleteResponse'>
type MemberListParams = NonNullable<paths['/api/v1/rbac/members']['get']['parameters']['query']>
type GroupListParams = NonNullable<paths['/api/v1/groups/']['get']['parameters']['query']>
type GroupMemberListParams = NonNullable<paths['/api/v1/groups/{group_id}/members']['get']['parameters']['query']>

const GROUP_PAGE_SIZE = 1000

const tenantMemberSchema = z.looseObject({
  id: z.string().min(1),
  tenant_id: z.string().min(1),
  user_id: z.string(),
  username: z.string().nullable(),
  email: z.string().nullable(),
  role: z.string(),
  is_active: z.boolean(),
  is_current: z.boolean(),
  created_at: dateTimeSchema,
  updated_at: dateTimeSchema,
}) satisfies z.ZodType<TenantMember>

const tenantMemberListSchema = z.looseObject({
  total: integerSchema.nonnegative(),
  items: z.array(tenantMemberSchema),
}) satisfies z.ZodType<OpenApiSchema<'TenantMemberListResponse'>>

const tenantMemberDeleteSchema = z.looseObject({
  user_id: z.string(),
  removed: z.boolean(),
  revoked_group_memberships: integerSchema.nonnegative(),
  revoked_dataset_permissions: integerSchema.nonnegative(),
  revoked_document_permissions: integerSchema.nonnegative(),
}) satisfies z.ZodType<TenantMemberDeleteResponse>

const tenantGroupSchema = z.looseObject({
  id: z.string().min(1),
  tenant_id: z.string().min(1),
  name: z.string(),
  external_id: z.string().nullish(),
  created_at: dateTimeSchema,
  updated_at: dateTimeSchema.nullish(),
}) satisfies z.ZodType<TenantGroupOut>

const tenantGroupListSchema = z.looseObject({
  total: integerSchema.nonnegative(),
  items: z.array(tenantGroupSchema),
}) satisfies z.ZodType<TenantGroupListResponse>

const tenantGroupMemberListSchema = z.looseObject({
  total: integerSchema.nonnegative(),
  items: z.array(z.looseObject({ user_id: z.string(), created_at: dateTimeSchema })),
}) satisfies z.ZodType<TenantGroupMemberListResponse>

const tenantGroupMembersUpdateSchema = z.looseObject({
  updated: integerSchema.nonnegative(),
}) satisfies z.ZodType<TenantGroupMembersUpdateResponse>

export const rbacApi = {
  async getCurrentTenantAccess(options?: ApiRequestOptions): Promise<TenantAccess> {
    const { data } = await apiClient.get<TenantAccess>('/rbac/me', { signal: options?.signal })
    return data
  },

  async listTenantMembers(params: MemberListParams = {}, options?: ApiRequestOptions) {
    const response = await apiClient.get<unknown>('/rbac/members', { params, signal: options?.signal })
    return parseApiResponse(response, tenantMemberListSchema, 'TenantMemberList')
  },

  async patchTenantMemberRole(userId: string, payload: TenantMemberUpdateRequest): Promise<TenantMember> {
    const response = await apiClient.patch<unknown>(`/rbac/members/${encodeURIComponent(userId)}`, payload)
    const member = parseApiResponse(response, tenantMemberSchema, 'TenantMember')
    if (member.user_id !== userId.trim() || member.role !== payload.role.trim().toLowerCase()) {
      throw new Error('角色修改回执与提交内容不一致，请先刷新成员列表')
    }
    return member
  },

  async removeTenantMember(userId: string): Promise<TenantMemberDeleteResponse> {
    const response = await apiClient.delete<unknown>(`/rbac/members/${encodeURIComponent(userId)}`)
    const receipt = parseApiResponse(response, tenantMemberDeleteSchema, 'TenantMemberDelete')
    if (receipt.user_id !== userId.trim()) throw new Error('移除回执的成员不匹配，请先刷新成员列表')
    return receipt
  },
}

export const groupApi = {
  async listGroups(params: GroupListParams = {}, options: ApiRequestOptions = {}): Promise<TenantGroupListResponse> {
    const response = await apiClient.get<unknown>('/groups', { params, signal: options.signal })
    return parseApiResponse(response, tenantGroupListSchema, 'TenantGroupList')
  },

  listAllGroups(options: ApiRequestOptions = {}): Promise<TenantGroupOut[]> {
    return readDirectoryPages(
      (params) => groupApi.listGroups(params, options),
      (group) => group.id,
      options.signal,
      GROUP_PAGE_SIZE,
    )
  },

  async createGroup(payload: TenantGroupCreateRequest): Promise<TenantGroupOut> {
    const response = await apiClient.post<unknown>('/groups', payload)
    return parseApiResponse(response, tenantGroupSchema, 'TenantGroup')
  },

  async getGroup(groupId: string, options?: ApiRequestOptions): Promise<TenantGroupOut> {
    const response = await apiClient.get<unknown>(`/groups/${encodeURIComponent(groupId)}`, {
      signal: options?.signal,
    })
    const group = parseApiResponse(response, tenantGroupSchema, 'TenantGroup')
    if (!matchesResourceId(group.id, groupId)) throw new Error('返回的群组不匹配，请重新读取')
    return group
  },

  async patchGroup(groupId: string, payload: TenantGroupUpdateRequest): Promise<TenantGroupOut> {
    const response = await apiClient.patch<unknown>(`/groups/${encodeURIComponent(groupId)}`, payload)
    const group = parseApiResponse(response, tenantGroupSchema, 'TenantGroup')
    if (!matchesResourceId(group.id, groupId)) throw new Error('保存回执的群组不匹配，请刷新后核对')
    return group
  },

  async deleteGroup(groupId: string): Promise<void> {
    await apiClient.delete(`/groups/${encodeURIComponent(groupId)}`)
  },

  async listGroupMembers(
    groupId: string,
    params: GroupMemberListParams = {},
    options?: ApiRequestOptions,
  ): Promise<TenantGroupMemberListResponse> {
    const response = await apiClient.get<unknown>(`/groups/${encodeURIComponent(groupId)}/members`, {
      params,
      signal: options?.signal,
    })
    return parseApiResponse(response, tenantGroupMemberListSchema, 'TenantGroupMemberList')
  },

  async addGroupMembers(
    groupId: string,
    payload: TenantGroupMembersUpdateRequest,
  ): Promise<TenantGroupMembersUpdateResponse> {
    const response = await apiClient.post<unknown>(`/groups/${encodeURIComponent(groupId)}/members`, payload)
    return parseApiResponse(response, tenantGroupMembersUpdateSchema, 'TenantGroupMembersUpdate')
  },

  async removeGroupMembers(
    groupId: string,
    payload: TenantGroupMembersUpdateRequest,
  ): Promise<TenantGroupMembersUpdateResponse> {
    const response = await apiClient.post<unknown>(`/groups/${encodeURIComponent(groupId)}/members/remove`, payload)
    return parseApiResponse(response, tenantGroupMembersUpdateSchema, 'TenantGroupMembersUpdate')
  },
}
