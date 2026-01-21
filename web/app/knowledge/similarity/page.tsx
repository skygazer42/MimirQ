import { AppFrame } from '@/components/app-frame'
import { RagvizSimilarityWorkbench } from '@/components/ragviz/similarity-workbench'

export default function KnowledgeSimilarityPage() {
  return (
    <AppFrame mainClassName="overflow-hidden">
      <RagvizSimilarityWorkbench />
    </AppFrame>
  )
}

