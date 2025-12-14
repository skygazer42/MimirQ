'use client'
import ForceGraph3D from 'react-force-graph-3d'

const ForceGraph3DWrapper = ({ graphRef, ...props }: any) => {
  return <ForceGraph3D ref={graphRef} {...props} />
}

export default ForceGraph3DWrapper