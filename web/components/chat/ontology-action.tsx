'use client'

import { useState } from 'react'
import { OntologyActionForm } from '@/components/enterprise-ontology-action-form'
import { formatApiError } from '@/lib/api-errors'
import type { OntologyActionProposal } from '@/types/enterprise-ontology'

export function ChatOntologyAction({
  proposal,
  messageId,
}: Readonly<{ proposal: OntologyActionProposal; messageId: string }>) {
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run(label: string, task: () => Promise<void>) {
    setPending(label)
    setError(null)
    try {
      await task()
    } catch (failure) {
      setError(formatApiError(failure, label + '失败'))
    } finally {
      setPending(null)
    }
  }

  return (
    <details className="my-3 border-t border-border pt-3 text-sm">
      <summary className="cursor-pointer font-medium">准备{proposal.label}</summary>
      <fieldset className="my-3 grid min-w-0 gap-3" disabled={pending !== null}>
        <OntologyActionForm proposal={proposal} initialRequestId={messageId} run={run} />
      </fieldset>
      {pending && (
        <p role="status" className="text-muted-foreground">
          {pending}中…
        </p>
      )}
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
    </details>
  )
}
