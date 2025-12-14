import { GraphData, GraphNode, GraphLink } from '@/lib/graph-parser'

// Mock delay to simulate network request
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

export class GraphService {
  /**
   * Fetch the initial graph data (e.g., top entities or root nodes)
   */
  static async fetchInitialGraph(): Promise<GraphData> {
    await delay(800) // Simulate latency
    
    // Mock Data: Core Concepts
    const nodes: GraphNode[] = [
      { id: '1', label: 'Artificial Intelligence', group: 1, val: 20 },
      { id: '2', label: 'Machine Learning', group: 1, val: 15 },
      { id: '3', label: 'Deep Learning', group: 1, val: 10 },
      { id: '4', label: 'NLP', group: 2, val: 12 },
      { id: '5', label: 'Computer Vision', group: 3, val: 12 },
      { id: '6', label: 'Reinforcement Learning', group: 1, val: 10 }
    ]

    const links: GraphLink[] = [
      { source: '1', target: '2', label: 'includes' },
      { source: '2', target: '3', label: 'includes' },
      { source: '1', target: '4', label: 'application' },
      { source: '1', target: '5', label: 'application' },
      { source: '2', target: '6', label: 'includes' },
    ]

    return { nodes, links }
  }

  /**
   * Fetch neighbors for a specific node (Lazy Loading)
   */
  static async expandNode(nodeId: string): Promise<GraphData> {
    await delay(600)

    // Generate pseudo-random neighbors based on ID to be deterministic but look dynamic
    const count = Math.floor(Math.random() * 3) + 2 // 2 to 4 new neighbors
    const nodes: GraphNode[] = []
    const links: GraphLink[] = []

    for (let i = 0; i < count; i++) {
      const newId = `${nodeId}-${Date.now()}-${i}`
      const labels = ['Concept', 'Tool', 'Person', 'Paper', 'Organization']
      const labelType = labels[Math.floor(Math.random() * labels.length)]
      
      nodes.push({
        id: newId,
        label: `${labelType} ${Math.floor(Math.random() * 100)}`,
        group: Math.floor(Math.random() * 5),
        val: 5
      })

      links.push({
        source: nodeId,
        target: newId,
        label: 'related_to'
      })
    }

    return { nodes, links }
  }

  /**
   * Search for nodes by query
   */
  static async searchNodes(query: string): Promise<GraphNode[]> {
    await delay(300)
    // In a real app, this would query the backend. 
    // Here we just return empty as we handle client-side search in the component for now,
    // or we could mock a global search result.
    return [] 
  }
}
