import { apiClient } from './core'
import type {
  ExternalConversationIngestRequest,
  ExternalConversationIngestResponse,
} from '@/types/backend'

export type {
  ExternalConversationIngestRequest,
  ExternalConversationIngestResponse,
  ExternalConversationMessageInput,
} from '@/types/backend'

export const integrationApi = {
  async ingestConversationHistory(
    payload: ExternalConversationIngestRequest
  ): Promise<ExternalConversationIngestResponse> {
    const { data } = await apiClient.post('/integrations/conversations/ingest', payload)
    return data
  },
}
