import { PerspectiveCamera, Vector3 } from 'three'
import { describe, expect, it } from 'vitest'
import { getInitialGraphCamera } from './graph-camera'

describe('initial graph camera', () => {
  it('separates nodes that would overlap when viewed along the depth axis', () => {
    const nodes = [
      { x: 0, y: 0, z: -30 },
      { x: 0, y: 0, z: 0 },
      { x: 0, y: 0, z: 30 },
    ]
    const before = structuredClone(nodes)
    const view = getInitialGraphCamera(nodes, 900, 600)
    const camera = new PerspectiveCamera(50, 1.5, 0.1, 10000)
    camera.position.copy(new Vector3(view.position.x, view.position.y, view.position.z))
    camera.lookAt(view.target.x, view.target.y, view.target.z)
    camera.updateMatrixWorld()
    const projected = nodes.map((node) => new Vector3(node.x, node.y, node.z).project(camera))
    for (let index = 0; index < projected.length; index++) {
      for (let next = index + 1; next < projected.length; next++) {
        expect(
          Math.hypot(projected[index].x - projected[next].x, projected[index].y - projected[next].y),
        ).toBeGreaterThan(0.1)
      }
    }
    expect(nodes).toEqual(before)
  })

  it('keeps translated and coincident node sets finite and centred', () => {
    const view = getInitialGraphCamera(
      [
        { x: 300, y: 200, z: 100 },
        { x: 300, y: 200, z: 100 },
      ],
      600,
      400,
    )
    expect(view.target).toEqual({ x: 300, y: 200, z: 100 })
    expect(Object.values(view.position).every(Number.isFinite)).toBe(true)
    expect(view.position).not.toEqual(view.target)
  })
})
