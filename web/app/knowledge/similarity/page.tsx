import { Navbar } from '@/components/navbar'
import { RagvizSimilarityWorkbench } from '@/components/ragviz/similarity-workbench'

export default function KnowledgeSimilarityPage() {
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Navbar />
      <main className="flex-1 overflow-hidden">
        <RagvizSimilarityWorkbench />
      </main>
    </div>
  )
}

