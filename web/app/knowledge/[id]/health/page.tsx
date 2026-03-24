import DocumentHealthPage from '@/components/knowledge/document-health-page'

export default async function KnowledgeDocumentHealthPage({
  params,
}: Readonly<{
  params: Promise<{ id: string }>
}>) {
  const { id } = await params
  return <DocumentHealthPage documentId={id} />
}
