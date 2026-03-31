import { expose } from 'comlink'

import { parseGraphML } from '@/lib/graph-parser'

const api = {
  parseGraphML,
}

export type GraphParserWorkerApi = typeof api

expose(api)
