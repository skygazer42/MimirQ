import type { OpenApiSchema } from '@/types/backend'

import { apiClient } from '@/lib/api/core'

export type PromptTemplate = OpenApiSchema<'PromptTemplateOut'>
type PromptTemplateCreateSchema = OpenApiSchema<'PromptTemplateCreate'>
type PromptTemplateUpdateSchema = OpenApiSchema<'PromptTemplateUpdate'>
type PromptTemplateNewVersionSchema = OpenApiSchema<'PromptTemplateNewVersion'>

export type PromptTemplateCreate = Omit<
  PromptTemplateCreateSchema,
  | 'template_key'
  | 'description'
  | 'category'
  | 'version'
  | 'ab_experiment_key'
  | 'ab_variant'
  | 'ab_weight'
> & {
  template_key?: string
  description?: string
  category?: string
  version?: number
  ab_experiment_key?: string
  ab_variant?: string
  ab_weight?: number
}

export type PromptTemplateUpdate = Omit<
  PromptTemplateUpdateSchema,
  'template_key' | 'description' | 'category' | 'ab_experiment_key' | 'ab_variant'
> & {
  template_key?: string
  description?: string
  category?: string
  ab_experiment_key?: string
  ab_variant?: string
}

export type PromptTemplateNewVersion = Omit<
  PromptTemplateNewVersionSchema,
  'description' | 'category' | 'ab_experiment_key' | 'ab_variant'
> & {
  description?: string
  category?: string
  ab_experiment_key?: string
  ab_variant?: string
}
export type PromptTemplateBuiltinSyncResponse = OpenApiSchema<'BuiltinPromptTemplateSyncResponse'>

export const promptTemplateApi = {
  async create(params: PromptTemplateCreate): Promise<PromptTemplate> {
    const { data } = await apiClient.post('/prompt-templates', params)
    return data
  },

  async list(params?: {
    skip?: number
    limit?: number
    category?: string
    is_active?: boolean
  }): Promise<{ total: number; items: PromptTemplate[] }> {
    const { data } = await apiClient.get('/prompt-templates', { params })
    return data
  },

  async get(templateId: string): Promise<PromptTemplate> {
    const { data } = await apiClient.get(`/prompt-templates/${templateId}`)
    return data
  },

  async update(templateId: string, params: PromptTemplateUpdate): Promise<PromptTemplate> {
    const { data } = await apiClient.put(`/prompt-templates/${templateId}`, params)
    return data
  },

  async delete(templateId: string): Promise<void> {
    await apiClient.delete(`/prompt-templates/${templateId}`)
  },

  async duplicate(templateId: string): Promise<PromptTemplate> {
    const { data } = await apiClient.post(`/prompt-templates/${templateId}/duplicate`)
    return data
  },

  async createVersion(templateId: string, params: PromptTemplateNewVersion): Promise<PromptTemplate> {
    const { data } = await apiClient.post(`/prompt-templates/${templateId}/versions`, params)
    return data
  },

  async syncBuiltins(): Promise<PromptTemplateBuiltinSyncResponse> {
    const { data } = await apiClient.post('/prompt-templates/builtins/sync')
    return data
  },
}
