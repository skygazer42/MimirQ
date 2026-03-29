import type { HealthResponse, ReadyResponse } from '@/types'

import { openapiRequest } from '@/lib/api/core'

export const healthApi = {
  async health(): Promise<HealthResponse> {
    return openapiRequest({ path: '/api/v1/health', method: 'get' })
  },

  async ready(): Promise<ReadyResponse> {
    return openapiRequest({ path: '/api/v1/health/ready', method: 'get' })
  },
}
