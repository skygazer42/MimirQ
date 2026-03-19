import DocumentHealthPage from '@/components/knowledge/document-health-page'

export default function KnowledgeDocumentHealthPage({ params }: Readonly<{ params: { id: string } }>) {
  return <DocumentHealthPage documentId={params.id} />
}

