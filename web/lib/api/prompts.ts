import { apiClient } from '@/lib/api/core'

export interface PromptTemplate {
  id: string
  tenant_id: string
  template_key?: string | null
  name: string
  description?: string
  content: string
  variables: string[]
  is_system: boolean
  is_active: boolean
  category?: string
  tags: string[]
  usage_count: number
  version?: number
  parent_id?: string | null
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight?: number
  created_at: string
  updated_at: string
}

export interface PromptTemplateCreate {
  name: string
  description?: string
  content: string
  variables?: string[]
  category?: string
  tags?: string[]
  is_active?: boolean
}

export interface PromptTemplateUpdate {
  name?: string
  description?: string
  content?: string
  variables?: string[]
  category?: string
  tags?: string[]
  is_active?: boolean
}

export interface PromptTemplateNewVersion {
  name?: string
  description?: string
  content?: string
  variables?: string[]
  category?: string
  tags?: string[]
  is_active?: boolean
  deactivate_previous?: boolean
  ab_experiment_key?: string
  ab_variant?: string
  ab_weight?: number
}

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
}
