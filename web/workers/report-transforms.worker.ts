import { expose } from 'comlink'

import { flattenFolderTree } from '@/lib/report-transforms'

const api = {
  flattenFolderTree,
}

export type ReportTransformsWorkerApi = typeof api

expose(api)
