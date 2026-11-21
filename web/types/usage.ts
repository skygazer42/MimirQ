import type { OpenApiSchema } from './backend'
import type { paths } from './openapi'

export type UsageWindowParams = NonNullable<paths['/api/v1/usage/chat/tokens/summary']['get']['parameters']['query']>

export type ChatTokenUsageRow = Omit<OpenApiSchema<'ChatTokenUsageRow'>, 'dataset_id'> & { dataset_id: string | null }
export type ChatTokenUsageSummary = Omit<OpenApiSchema<'ChatTokenUsageSummary'>, 'by_dataset'> & {
  by_dataset: ChatTokenUsageRow[]
}
export type ChatCostUsageRow = Omit<OpenApiSchema<'ChatCostUsageRow'>, 'dataset_id'> & { dataset_id: string | null }
export type ChatCostUsageSummary = Omit<OpenApiSchema<'ChatCostUsageSummary'>, 'by_dataset'> & {
  by_dataset: ChatCostUsageRow[]
}

export type ChatTokenQuotaStatus = OpenApiSchema<'ChatTokenQuotaStatus'>
export type TenantDocumentQuotaStatus = OpenApiSchema<'TenantDocumentQuotaStatus'>
export type TenantStorageQuotaStatus = OpenApiSchema<'TenantStorageQuotaStatus'>
export type TenantEmbeddingCharQuotaStatus = OpenApiSchema<'TenantEmbeddingCharQuotaStatus'>
export type TenantQpsQuotaConfig = OpenApiSchema<'TenantQpsQuotaConfig'>
export type TenantQuotaSummary = OpenApiSchema<'TenantQuotaSummary'>
