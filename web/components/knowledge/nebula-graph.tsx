'use client'

import { useEffect, type MutableRefObject } from 'react'
import ForceGraph3D, { type ForceGraphMethods, type ForceGraphProps } from 'react-force-graph-3d'

// Use a normal prop across Next's lazy boundary so camera methods reach the graph.
export function NebulaGraph({ graphRef, onReady, ...props }: ForceGraphProps & {
  graphRef: MutableRefObject<ForceGraphMethods | undefined>
  onReady: () => void
}) {
  useEffect(() => { onReady() }, [onReady])
  return <ForceGraph3D {...props} ref={graphRef} />
}
