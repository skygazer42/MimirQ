export type ChunkKeyboardNavigationInput = {
  key: string
  matchCount: number
  matchCursor: number
  loadedChunkCount: number
  highlightIndex: number
}

export type ChunkKeyboardNavigationAction =
  | { type: 'match'; nextIndex: number }
  | { type: 'chunk'; nextIndex: number }
  | null

function normalizeLoopIndex(value: number, length: number) {
  return ((value % length) + length) % length
}

export function resolveChunkKeyboardNavigation(
  input: Readonly<ChunkKeyboardNavigationInput>
): ChunkKeyboardNavigationAction {
  const key = String(input.key || '').toLowerCase()
  if (key !== 'j' && key !== 'k') return null

  const delta = key === 'j' ? 1 : -1

  if (input.matchCount > 0) {
    return {
      type: 'match',
      nextIndex: normalizeLoopIndex(input.matchCursor + delta, input.matchCount),
    }
  }

  if (input.loadedChunkCount <= 0) return null

  const anchorIndex =
    input.highlightIndex >= 0
      ? input.highlightIndex
      : delta > 0
        ? -1
        : 0

  return {
    type: 'chunk',
    nextIndex: normalizeLoopIndex(anchorIndex + delta, input.loadedChunkCount),
  }
}
