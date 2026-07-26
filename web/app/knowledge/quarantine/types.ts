export type QuarantineAction = 'release' | 'retry' | 'delete' | 'review' | 'tune'
export type ActingState = { id: string; action: QuarantineAction } | null
export type ReviewState = 'all' | 'pending' | 'reviewed'
export type JsonRecord = Record<string, unknown>
export type UserMetadata = JsonRecord & { quarantine_reviewed?: boolean }
export type QueueSyncStatus = {
  type: 'success' | 'error'
  message: string
  at: string
}

export type QuarantineSeverity = '高' | '中' | '低'
