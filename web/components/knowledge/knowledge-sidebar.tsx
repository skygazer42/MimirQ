'use client'

// Explicit wrapper to disambiguate the "knowledge library" sidebar from other sidebars
// (e.g. chunk-preview workbench sidebar).
import { Sidebar } from '@/components/sidebar'

export function KnowledgeSidebar() {
  return <Sidebar variant="workbench" />
}
