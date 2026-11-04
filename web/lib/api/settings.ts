import { apiClient } from '@/lib/api/core'
import type {
  SettingsUpdateResponse,
  SystemSettings,
  SystemStatus,
  TestLLMRequest,
  TestLLMResponse,
  UpdateSettingsRequest,
} from '@/types/settings'

export type {
  CacheConfig,
  ChatConfig,
  DifyExternalKnowledgeConfig,
  DoclingConfig,
  EmbeddingConfig,
  Etl4LlmConfig,
  FeatureFlags,
  GovernanceConfig,
  KGConfig,
  LangGraphConfig,
  LLMConfig,
  MagicPDFConfig,
  MarkerConfig,
  MilvusConfig,
  MinIOConfig,
  MinerUConfig,
  NavigationConfig,
  ObservabilityConfig,
  PaddleVLConfig,
  ParserBackendStatus,
  RAGConfig,
  SafetyConfig,
  SettingsUpdateResponse,
  SystemSettings,
  SystemStatus,
  TestLLMRequest,
  TestLLMResponse,
  TextInConfig,
  UpdateSettingsRequest,
  UrlIngestConfig,
} from '@/types/settings'

export async function getSettings(): Promise<SystemSettings> {
  const { data } = await apiClient.get('/settings')
  return data
}

export async function updateSettings(settings: UpdateSettingsRequest): Promise<SettingsUpdateResponse> {
  const { data } = await apiClient.put('/settings', settings)
  return data
}

export async function getSystemStatus(): Promise<SystemStatus> {
  const { data } = await apiClient.get('/settings/status')
  return data
}

export async function testLLMConnection(params: TestLLMRequest): Promise<TestLLMResponse> {
  const { data } = await apiClient.post('/settings/llm/test', params)
  return data
}

export const settingsApi = {
  get: getSettings,
  update: updateSettings,
  getStatus: getSystemStatus,
  testLLM: testLLMConnection,
}
