export function createSseDataParser() {
  let buffer = ''

  function feed(chunk: string): string[] {
    if (!chunk) return []

    buffer += chunk.replaceAll(/\r\n/g, '\n')
    const out: string[] = []

    while (true) {
      const sepIdx = buffer.indexOf('\n\n')
      if (sepIdx < 0) break

      const block = buffer.slice(0, sepIdx)
      buffer = buffer.slice(sepIdx + 2)

      const lines = block.split('\n')
      const dataLines = lines
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())

      if (dataLines.length) {
        out.push(dataLines.join('\n'))
      }
    }

    return out
  }

  function reset() {
    buffer = ''
  }

  return { feed, reset }
}

