import { describe, expect, it } from 'vitest'
import { fitNebulaCamera } from './nebula-camera'

describe('Nebula viewport fit', () => {
  const points = [{ x: 80, y: -20, z: 10, radius: 3 }, { x: 110, y: 15, z: -12, radius: 3 }, { x: 140, y: -10, z: 20, radius: 3 }, { x: 160, y: 20, z: 0, radius: 3 }]
  it.each([[359, 610], [832, 700], [1336, 866]])('fits every loaded sphere in a %s×%s viewport with padding', (width, height) => {
    const view = fitNebulaCamera(points, width, height, 50)!
    const vertical = Math.tan(50 * Math.PI / 360)
    const horizontal = vertical * width / height
    const padding = Math.min(32, width / 4, height / 4)
    for (const point of points) {
      const depth = view.position.z - point.z
      expect(Math.abs(point.x - view.target.x) + point.radius).toBeLessThanOrEqual(depth * horizontal * (1 - padding * 2 / width))
      expect(Math.abs(point.y - view.target.y) + point.radius).toBeLessThanOrEqual(depth * vertical * (1 - padding * 2 / height))
    }
    expect(view.position.x).toBe(view.target.x)
    expect(view.target.x).toBe(120)
  })
  it('does not move an empty canvas', () => expect(fitNebulaCamera([], 359, 610, 50)).toBeNull())
})
