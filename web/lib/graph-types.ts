export type GraphNode = {
  id: string
  label: string
  val?: number // size
  color?: string
  group?: number
  kind?: unknown
  type?: unknown
  source?: unknown
  meta?: Record<string, unknown>
  x?: number
  y?: number
  z?: number
  fx?: number | null
  fy?: number | null
  fz?: number | null
  vx?: number | null
  vy?: number | null
  vz?: number | null
}

export type GraphLink = {
  source: string
  target: string
  id?: string | number | null
  label?: string
  kind?: unknown
  type?: unknown
  predicate?: unknown
  confidence?: unknown
  weight?: unknown
  value?: unknown
  score?: unknown
  color?: string
  index?: number
  meta?: Record<string, unknown>
}

export type GraphData = {
  nodes: GraphNode[]
  links: GraphLink[]
  ontologyVersionId?: string
}
