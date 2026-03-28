import { expose } from 'comlink'

import { computeConnectedComponents } from '@/lib/graph-clustering'

const api = {
  computeConnectedComponents,
}

export type GraphClusteringWorkerApi = typeof api

expose(api)

