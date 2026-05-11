import commonMessages from './zh-CN/common'
import chatMessages from './zh-CN/chat'
import documentsMessages from './zh-CN/documents'
import auditMessages from './zh-CN/audit'
import knowledgeMessages from './zh-CN/knowledge'
import chunkPreviewMessages from './zh-CN/chunk-preview'
import ingestionMessages from './zh-CN/ingestion'
import ragMessages from './zh-CN/rag'
import graphMessages from './zh-CN/graph'
import parsingMessages from './zh-CN/parsing'
import commandMessages from './zh-CN/command'
import governanceMessages from './zh-CN/governance'
import reportsMessages from './zh-CN/reports'

const zhCNMessages = {
  ...commonMessages,
  ...chatMessages,
  ...documentsMessages,
  ...auditMessages,
  ...knowledgeMessages,
  ...chunkPreviewMessages,
  ...ingestionMessages,
  ...ragMessages,
  ...graphMessages,
  ...parsingMessages,
  ...commandMessages,
  ...governanceMessages,
  ...reportsMessages,
} as const

export default zhCNMessages
