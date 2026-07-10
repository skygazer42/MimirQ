import { NavigationVisibilityGate } from '@/components/auth/navigation-visibility-gate'
import { RetrievalAblationsPage } from '@/components/evaluation/retrieval-ablations-page'

export default function EvaluationsAblationsPage() {
  return (
    <NavigationVisibilityGate moduleKey="ablations" pageName="检索调参对比">
      <RetrievalAblationsPage />
    </NavigationVisibilityGate>
  )
}
