import { VectorNebula } from "@/components/knowledge/vector-nebula"
import { AppFrame } from "@/components/app-frame"
import { DocumentViewerPanel } from "@/components/document-viewer-panel"

export default function NebulaPage() {
  return (
    <AppFrame rightPanel={<DocumentViewerPanel />} withDocumentViewerPadding>
      <VectorNebula />
    </AppFrame>
  )
}
