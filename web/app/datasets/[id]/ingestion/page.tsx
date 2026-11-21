import PolicyWorkspace from './policy-workspace'

export default async function DatasetIngestionPolicyPage({ params }: Readonly<{ params: Promise<{ id: string }> }>) {
  const { id } = await params
  return <PolicyWorkspace key={id} datasetId={id} />
}
