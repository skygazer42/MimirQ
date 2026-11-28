import { Vector3 } from 'three'

type Point = Readonly<{ x?: number; y?: number; z?: number }>

export function getInitialGraphCamera(points: readonly Point[], width: number, height: number) {
  const positions = points.map((point) => new Vector3(point.x ?? 0, point.y ?? 0, point.z ?? 0))
  const target = positions.reduce((sum, point) => sum.add(point), new Vector3()).divideScalar(positions.length)
  const directions = [
    [0, 0, 1],
    [1, 0, 1],
    [-1, 0, 1],
    [0, 0.7, 1],
    [1, 0.7, 1],
    [-1, 0.7, 1],
    [1, -0.7, 1],
    [-1, -0.7, 1],
  ] as const
  let best = new Vector3(0, 0, 1)
  let bestSeparation = -1
  for (const [x, y, z] of directions) {
    const direction = new Vector3(x, y, z).normalize()
    const right = new Vector3().crossVectors(new Vector3(0, 1, 0), direction).normalize()
    const up = new Vector3().crossVectors(direction, right)
    const projected = positions.map((point) => ({ x: point.dot(right), y: point.dot(up) }))
    const xs = projected.map((point) => point.x)
    const ys = projected.map((point) => point.y)
    const scale = Math.min(
      width / Math.max(1, Math.max(...xs) - Math.min(...xs)),
      height / Math.max(1, Math.max(...ys) - Math.min(...ys)),
    )
    let separation = Infinity
    for (let index = 0; index < projected.length; index++) {
      for (let next = index + 1; next < projected.length; next++) {
        const dx = projected[index].x - projected[next].x
        const dy = projected[index].y - projected[next].y
        separation = Math.min(separation, (dx * dx + dy * dy) * scale * scale)
      }
    }
    if (separation > bestSeparation) {
      bestSeparation = separation
      best = direction
    }
  }
  const radius = Math.max(...positions.map((point) => point.distanceTo(target)))
  const position = target.clone().addScaledVector(best, Math.max(100, radius * 4))
  return {
    position: { x: position.x, y: position.y, z: position.z },
    target: { x: target.x, y: target.y, z: target.z },
  }
}
