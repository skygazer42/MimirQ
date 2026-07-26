export type SimilarityTopKAxis = 'x' | 'y' | 'none'

export function computeThresholdMask(
  matrix: number[][],
  minSim: number,
  maxSim: number
) {
  const min = Math.min(minSim, maxSim)
  const max = Math.max(minSim, maxSim)
  return matrix.map((row) =>
    row.map((val) => Number.isFinite(val) && val >= min && val <= max)
  )
}

function matrixDimensions(matrix: readonly { length: number }[]) {
  const rows = matrix.length
  const cols = rows > 0 ? matrix[0]?.length || 0 : 0
  return { rows, cols }
}

function createBooleanMatrix(rows: number, cols: number, value: boolean) {
  return Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => value)
  )
}

function finiteRowScores(row: number[]) {
  return row
    .map((v, j) => ({ j, v }))
    .filter((x) => Number.isFinite(x.v))
    .sort((a, b) => b.v - a.v)
}

export function applyTopKByRow(
  matrix: number[][],
  mask: boolean[][],
  k: number
) {
  for (let i = 0; i < matrix.length; i++) {
    for (const { j } of finiteRowScores(matrix[i]).slice(0, k)) {
      mask[i][j] = true
    }
  }
}

function finiteColumnScores(matrix: number[][], columnIndex: number) {
  const scored = []
  for (let i = 0; i < matrix.length; i++) {
    const v = matrix[i][columnIndex]
    if (Number.isFinite(v)) scored.push({ i, v })
  }
  return scored.sort((a, b) => b.v - a.v)
}

export function applyTopKByColumn(
  matrix: number[][],
  mask: boolean[][],
  cols: number,
  k: number
) {
  for (let j = 0; j < cols; j++) {
    for (const { i } of finiteColumnScores(matrix, j).slice(0, k)) {
      mask[i][j] = true
    }
  }
}

export function computeTopKMask(
  matrix: number[][],
  topK: number,
  axis: 'x' | 'y'
) {
  const { rows, cols } = matrixDimensions(matrix)
  if (rows === 0 || cols === 0) return []
  if (!topK || topK <= 0) return createBooleanMatrix(rows, cols, true)

  const k = axis === 'x' ? Math.min(topK, cols) : Math.min(topK, rows)
  const mask = createBooleanMatrix(rows, cols, false)
  if (axis === 'x') applyTopKByRow(matrix, mask, k)
  if (axis === 'y') applyTopKByColumn(matrix, mask, cols, k)
  return mask
}

export function combineWithAND(a: boolean[][], b: boolean[][]) {
  const rows = Math.min(a.length, b.length)
  const cols = rows > 0 ? Math.min(a[0]?.length || 0, b[0]?.length || 0) : 0
  const out: boolean[][] = Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => false)
  )
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) out[i][j] = Boolean(a[i][j] && b[i][j])
  }
  return out
}

export function combineWithOR(masks: boolean[][][]) {
  if (masks.length === 0) return []
  const rows = masks[0].length
  const cols = rows > 0 ? masks[0][0].length : 0
  const out: boolean[][] = Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => false)
  )
  for (const mask of masks) {
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++)
        out[i][j] = out[i][j] || Boolean(mask[i][j])
    }
  }
  return out
}

export function computeFinalMask(
  matrix: number[][],
  range: { min: number; max: number },
  topK: { value: number; axis: 'x' | 'y' }
) {
  const thresholdMask = computeThresholdMask(matrix, range.min, range.max)
  const topKMask = computeTopKMask(matrix, topK.value, topK.axis)
  return combineWithAND(thresholdMask, topKMask)
}

export function applyMask(
  matrix: number[][],
  mask: boolean[][]
): Array<Array<number | null>> {
  const rows = Math.min(matrix.length, mask.length)
  const cols =
    rows > 0 ? Math.min(matrix[0]?.length || 0, mask[0]?.length || 0) : 0
  const out: Array<Array<number | null>> = Array.from({ length: rows }, () =>
    Array.from({ length: cols }, () => null)
  )
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      out[i][j] = mask[i][j] ? matrix[i][j] : null
    }
  }
  return out
}

export type NormalModeStats = {
  totalCount: number
  currentDisplayCount: number
  diagonalTrueCount: number
  diagonalTotalCount: number
  missingMatchCount: number
  topKAxis: SimilarityTopKAxis
}

function countTrueCells(mask: boolean[][], rows: number, cols: number) {
  let count = 0
  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      if (mask[i][j]) count++
    }
  }
  return count
}

function countTrueDiagonal(mask: boolean[][], diagonalTotalCount: number) {
  let count = 0
  for (let i = 0; i < diagonalTotalCount; i++) {
    if (mask[i][i]) count++
  }
  return count
}

function rowHasTrue(mask: boolean[][], rowIndex: number, cols: number) {
  for (let j = 0; j < cols; j++) {
    if (mask[rowIndex][j]) return true
  }
  return false
}

function columnHasTrue(mask: boolean[][], columnIndex: number, rows: number) {
  for (let i = 0; i < rows; i++) {
    if (mask[i][columnIndex]) return true
  }
  return false
}

function countRowsWithoutMatch(mask: boolean[][], rows: number, cols: number) {
  let count = 0
  for (let i = 0; i < rows; i++) {
    if (!rowHasTrue(mask, i, cols)) count++
  }
  return count
}

function countColumnsWithoutMatch(
  mask: boolean[][],
  rows: number,
  cols: number
) {
  let count = 0
  for (let j = 0; j < cols; j++) {
    if (!columnHasTrue(mask, j, rows)) count++
  }
  return count
}

function missingMatchCountByAxis(
  mask: boolean[][],
  rows: number,
  cols: number,
  topKAxis: SimilarityTopKAxis
) {
  if (topKAxis === 'x') return countRowsWithoutMatch(mask, rows, cols)
  if (topKAxis === 'y') return countColumnsWithoutMatch(mask, rows, cols)
  return 0
}

export function calculateNormalModeStatistics(
  finalMask: boolean[][],
  topKAxis: SimilarityTopKAxis
): NormalModeStats {
  const { rows, cols } = matrixDimensions(finalMask)
  const totalCount = rows * cols

  const diagonalTotalCount = Math.min(rows, cols)

  return {
    totalCount,
    currentDisplayCount: countTrueCells(finalMask, rows, cols),
    diagonalTrueCount: countTrueDiagonal(finalMask, diagonalTotalCount),
    diagonalTotalCount,
    missingMatchCount: missingMatchCountByAxis(finalMask, rows, cols, topKAxis),
    topKAxis,
  }
}

export type DifferenceModeStats = {
  truePositive: number
  trueNegative: number
  falsePositive: number
  falseNegative: number
  contextRecall: number
  contextPrecision: number
}

export function calculateDifferenceModeStatistics(
  groundTruthMask: boolean[][],
  currentMask: boolean[][]
): DifferenceModeStats {
  const rows = Math.min(groundTruthMask.length, currentMask.length)
  const cols =
    rows > 0
      ? Math.min(groundTruthMask[0]?.length || 0, currentMask[0]?.length || 0)
      : 0

  let truePositive = 0
  let trueNegative = 0
  let falsePositive = 0
  let falseNegative = 0

  for (let i = 0; i < rows; i++) {
    for (let j = 0; j < cols; j++) {
      const gt = Boolean(groundTruthMask[i][j])
      const cur = Boolean(currentMask[i][j])
      if (gt && cur) truePositive++
      else if (!gt && !cur) trueNegative++
      else if (!gt && cur) falsePositive++
      else falseNegative++
    }
  }

  const contextRecall =
    truePositive + falseNegative > 0
      ? truePositive / (truePositive + falseNegative)
      : 0
  const contextPrecision =
    truePositive + falsePositive > 0
      ? truePositive / (truePositive + falsePositive)
      : 0

  return {
    truePositive,
    trueNegative,
    falsePositive,
    falseNegative,
    contextRecall,
    contextPrecision,
  }
}

export function formatHeatmapValue(value: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  let formatted = value.toFixed(4)
  while (formatted.includes('.') && formatted.endsWith('0')) {
    formatted = formatted.slice(0, -1)
  }
  return formatted.endsWith('.') ? formatted.slice(0, -1) : formatted
}
