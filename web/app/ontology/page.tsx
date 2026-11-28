'use client'

import { useSyncExternalStore } from 'react'
import { AppFrame } from '@/components/app-frame'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { OntologyWorkspace } from './ontology-workspace'

export default function OntologyPage() {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return (
    <AppFrame>
      <OntologyWorkspace key={sessionKey} sessionKey={sessionKey} />
    </AppFrame>
  )
}
