"use client"

import { DocumentViewerPanelShell } from "@/components/document-viewer/document-viewer-panel-shell"
import { useDocumentViewerPanelState } from "@/components/document-viewer/use-document-viewer-panel-state"

export function DocumentViewerPanel() {
  const state = useDocumentViewerPanelState()
  return <DocumentViewerPanelShell {...state} />
}
