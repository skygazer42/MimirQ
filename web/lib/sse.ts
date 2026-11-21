export function createSseDataParser() {
  let line = ''
  let dataLines: string[] = []
  let skipLineFeed = false

  function readLine(events: string[]) {
    if (line.length === 0) {
      if (dataLines.length > 0) events.push(dataLines.join('\n'))
      dataLines = []
      return
    }
    const separator = line.indexOf(':')
    const field = separator === -1 ? line : line.slice(0, separator)
    if (field !== 'data') return

    let value = separator === -1 ? '' : line.slice(separator + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    dataLines.push(value)
  }

  function feed(chunk: string): string[] {
    const events: string[] = []
    for (const character of chunk) {
      if (skipLineFeed) {
        skipLineFeed = false
        if (character === '\n') continue
      }
      if (character === '\r' || character === '\n') {
        readLine(events)
        line = ''
        skipLineFeed = character === '\r'
      } else {
        line += character
      }
    }
    return events
  }

  return { feed }
}
