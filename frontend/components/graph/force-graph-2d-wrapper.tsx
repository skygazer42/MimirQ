'use client'
import ForceGraph2D from 'react-force-graph-2d'

const ForceGraph2DWrapper = ({ graphRef, ...props }: any) => {
  return <ForceGraph2D ref={graphRef} {...props} />
}

export default ForceGraph2DWrapper