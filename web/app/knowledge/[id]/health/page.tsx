import DocumentHealthPage from '@/components/knowledge/document-health-page'

type KnowledgeDocumentHealthPageProps = {
  params: Promise<{ id: string }>
}

export default async function KnowledgeDocumentHealthPage({ params }: Readonly<KnowledgeDocumentHealthPageProps>) {
  const { id } = await params
  return <DocumentHealthPage documentId={id} />
}
