'use client'

import { useParams } from 'next/navigation'
import PolicyWorkspace from './policy-workspace'

export default function DatasetIngestionPolicyPage() {
  const { id } = useParams<{ id: string }>()
  return <PolicyWorkspace key={id} datasetId={id} />
}
