import { NavigationVisibilityGate } from '@/components/auth/navigation-visibility-gate'
import { KGSnapshotsPage } from '@/components/graph/kg-snapshots-page'

export default function GraphSnapshotsRoute() {
  return (
    <NavigationVisibilityGate moduleKey="graphSnapshots" pageName="图谱快照">
      <KGSnapshotsPage />
    </NavigationVisibilityGate>
  )
}
