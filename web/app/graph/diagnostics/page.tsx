import { NavigationVisibilityGate } from '@/components/auth/navigation-visibility-gate'
import { KGDiagnosticsPage } from '@/components/graph/kg-diagnostics-page'

export default function GraphDiagnosticsRoute() {
  return (
    <NavigationVisibilityGate moduleKey="graphDiagnostics" pageName="图谱检索评测">
      <KGDiagnosticsPage />
    </NavigationVisibilityGate>
  )
}
