/** Unicode positions used by JavaScript text views. */
export function createCodePointToUtf16Converter(text: string) {
  const surrogatePairPositions: number[] = []
  let codePointLength = 0
  for (const character of text) {
    if (character.length === 2) surrogatePairPositions.push(codePointLength)
    codePointLength += 1
  }

  function toUtf16(offset: number): number | undefined {
    if (!Number.isInteger(offset) || offset < 0 || offset > codePointLength) return undefined
    let low = 0
    let high = surrogatePairPositions.length
    while (low < high) {
      const middle = Math.floor((low + high) / 2)
      if (surrogatePairPositions[middle] < offset) low = middle + 1
      else high = middle
    }
    return offset + low
  }

  return { codePointLength, toUtf16 }
}

/** Limit lowercase matches, then merge overlapping whole-character ranges in the original text. */
export function findCaseInsensitiveTextRanges(text: string, query: string, limit: number) {
  if (query.length === 0 || limit === 0) return []
  const lowerText = text.toLowerCase()
  const lowerQuery = query.toLowerCase()
  let match = lowerText.indexOf(lowerQuery)
  if (match < 0) return []
  const starts: number[] = []
  const ends: number[] = []
  let offset = 0
  for (const character of text) {
    const end = offset + character.length
    const lowercaseLength = character.toLowerCase().length
    for (let index = 0; index < lowercaseLength; index += 1) {
      starts.push(offset)
      ends.push(end)
    }
    offset = end
  }
  const ranges: Array<{ start: number; end: number }> = []
  let matchCount = 0
  while (match >= 0 && matchCount < limit) {
    const range = { start: starts[match], end: ends[match + lowerQuery.length - 1] }
    const previousRange = ranges[ranges.length - 1]
    if (previousRange !== undefined && range.start < previousRange.end) {
      previousRange.end = Math.max(previousRange.end, range.end)
    } else {
      ranges.push(range)
    }
    matchCount += 1
    match = lowerText.indexOf(lowerQuery, match + lowerQuery.length)
  }
  return ranges
}

/** Expand a bounded UTF-16 view range only when an edge splits a surrogate pair. */
export function expandTextRangeToCharacters(text: string, start: number, end: number) {
  const surrogatePair = /^[\uD800-\uDBFF][\uDC00-\uDFFF]$/
  return {
    start: surrogatePair.test(text.slice(start - 1, start + 1)) ? start - 1 : start,
    end: surrogatePair.test(text.slice(end - 1, end + 1)) ? end + 1 : end,
  }
}
