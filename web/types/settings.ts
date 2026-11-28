/** Settings-domain types derived from the backend API schemas. */

import type { OpenApiSchema } from './backend'

export type FeatureFlags = OpenApiSchema<'FeatureFlags'>
export type KGConfig = OpenApiSchema<'KGConfig'>
export type LLMConfig = OpenApiSchema<'LLMConfig'>
export type EmbeddingConfig = OpenApiSchema<'EmbeddingConfig'>
export type MilvusConfig = OpenApiSchema<'MilvusConfig'>
export type MinIOConfig = OpenApiSchema<'MinioConfig'>
export type RAGConfig = OpenApiSchema<'RAGConfig'>
export type CacheConfig = OpenApiSchema<'CacheConfig'>
export type UrlIngestStatus = OpenApiSchema<'UrlIngestStatus'>
export type GovernanceConfig = OpenApiSchema<'GovernanceConfig'>
export type MinerUConfig = OpenApiSchema<'MinerUConfig'>
export type Etl4LlmConfig = OpenApiSchema<'Etl4LlmConfig'>
export type MarkerConfig = OpenApiSchema<'MarkerConfig'>
export type DoclingConfig = OpenApiSchema<'DoclingConfig'>
export type PaddleVLConfig = OpenApiSchema<'PaddleVLConfig'>
export type TextInConfig = OpenApiSchema<'TextInConfig'>
export type MagicPDFConfig = OpenApiSchema<'MagicPDFConfig'>
export type ObservabilityConfig = OpenApiSchema<'ObservabilityConfig'>
export type SafetyConfig = OpenApiSchema<'SafetyConfig'>
export type ChatConfig = OpenApiSchema<'ChatConfig'>
export type LangGraphConfig = OpenApiSchema<'LangGraphConfig'>
export type NavigationConfig = OpenApiSchema<'NavigationConfig'>
export type DifyExternalKnowledgeConfig = OpenApiSchema<'DifyExternalKnowledgeConfig'>
export type SystemSettings = OpenApiSchema<'SystemSettings'>
export type UpdateSettingsRequest = OpenApiSchema<'UpdateSettingsRequest'>

type BackendTestLLMRequest = OpenApiSchema<'TestLLMRequest'>

export type TestLLMRequest = Pick<BackendTestLLMRequest, 'api_key' | 'model'> &
  Partial<Omit<BackendTestLLMRequest, 'api_key' | 'model'>>

export type SettingsUpdateResponse = OpenApiSchema<'UpdateSettingsResponse'>
export type TestLLMResponse = OpenApiSchema<'TestLLMResponse'>

export type ParserBackendStatus = OpenApiSchema<'SettingsParserStatus'>

export type SystemStatus = OpenApiSchema<'SystemStatusResponse'>
