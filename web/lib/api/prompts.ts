import type { OpenApiSchema } from '@/types/backend'
import type { OpenApiQueryParams } from '@/types/openapi-helpers'

import { apiClient, type ApiRequestOptions } from '@/lib/api/core'

export type PromptTemplate = OpenApiSchema<'PromptTemplateOut'>
type PromptTemplateCreateSchema = OpenApiSchema<'PromptTemplateCreate'>
type PromptTemplateUpdateSchema = OpenApiSchema<'PromptTemplateUpdate'>
type PromptTemplateNewVersionSchema = OpenApiSchema<'PromptTemplateNewVersion'>

export type PromptTemplateCreate = Omit<
  PromptTemplateCreateSchema,
  'template_key' | 'version' | 'ab_experiment_key' | 'ab_variant' | 'ab_weight'
> & {
  template_key?: string
  version?: number
  ab_experiment_key?: string
  ab_variant?: string
  ab_weight?: number
}

export type PromptTemplateUpdate = Omit<
  PromptTemplateUpdateSchema,
  'template_key' | 'ab_experiment_key' | 'ab_variant'
> & {
  template_key?: string
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
type PromptTemplateBuiltinSyncResponse = OpenApiSchema<'BuiltinPromptTemplateSyncResponse'>
type PromptTemplateListParams = NonNullable<OpenApiQueryParams<'/api/v1/prompt-templates', 'get'>>

export const promptTemplateApi = {
  async create(params: PromptTemplateCreate): Promise<PromptTemplate> {
    const { data } = await apiClient.post('/prompt-templates', params)
    return data
  },

  async list(
    params?: PromptTemplateListParams,
    options?: ApiRequestOptions,
  ): Promise<OpenApiSchema<'PromptTemplateList'>> {
    const { data } = await apiClient.get('/prompt-templates', { params, signal: options?.signal })
    return data
  },

  async listAll(
    params?: Omit<PromptTemplateListParams, 'skip' | 'limit'>,
    options?: ApiRequestOptions,
  ): Promise<OpenApiSchema<'PromptTemplateList'>> {
    const templates = new Map<string, PromptTemplate>()
    let skip = 0
    let page = await promptTemplateApi.list({ ...params, skip, limit: 100 }, options)
    const total = page.total
    for (;;) {
      if (page.total !== total) throw new Error('模板列表有变化，请重新加载。')
      const previousCount = templates.size
      for (const template of page.items) {
        if (!templates.has(template.id)) templates.set(template.id, template)
      }
      skip += page.items.length
      if (skip >= total) break
      if (templates.size === previousCount) throw new Error('模板列表未完整加载，请重试。')

      options?.signal?.throwIfAborted()
      page = await promptTemplateApi.list({ ...params, skip, limit: 100 }, options)
    }
    if (templates.size !== total) throw new Error('模板列表有变化，请重新加载。')
    return { items: [...templates.values()], total }
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
