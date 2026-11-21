type VisibleSphere = { x: number; y: number; z: number; radius: number }

export function fitNebulaCamera(points: readonly VisibleSphere[], width: number, height: number, fieldOfView: number) {
  if (points.length === 0) return null
  const target = {
    x: (Math.min(...points.map((point) => point.x)) + Math.max(...points.map((point) => point.x))) / 2,
    y: (Math.min(...points.map((point) => point.y)) + Math.max(...points.map((point) => point.y))) / 2,
    z: (Math.min(...points.map((point) => point.z)) + Math.max(...points.map((point) => point.z))) / 2,
  }
  const radius = Math.max(
    ...points.map((point) => Math.hypot(point.x - target.x, point.y - target.y, point.z - target.z) + point.radius),
  )
  const padding = Math.min(32, width / 4, height / 4)
  const verticalTangent = Math.tan((fieldOfView * Math.PI) / 360)
  const horizontalTangent = (verticalTangent * width) / height
  const halfAngle = Math.atan(
    Math.min(verticalTangent * (1 - (2 * padding) / height), horizontalTangent * (1 - (2 * padding) / width)),
  )
  return { target, position: { x: target.x, y: target.y, z: target.z + radius / Math.sin(halfAngle) } }
}
