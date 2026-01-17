import { VectorNebula } from "@/components/knowledge/vector-nebula"
import { Navbar } from "@/components/navbar"
import { DocumentViewerPanel } from "@/components/document-viewer-panel"

export default function NebulaPage() {
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Navbar />
      <main className="flex-1 relative">
        <VectorNebula />
      </main>
      <DocumentViewerPanel />
    </div>
  )
}
