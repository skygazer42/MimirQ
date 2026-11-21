const PRESET_SEPARATORS: Record<string, string> = {
  paragraph: '\n\n',
  line: '\n',
  sentence_cn: '。',
  sentence_en: '.',
  markdown_hr: '---',
  markdown_h1: '# ',
  markdown_h2: '## ',
}

export function getPresetSeparator(preset: string): string {
  return Object.hasOwn(PRESET_SEPARATORS, preset) ? PRESET_SEPARATORS[preset] : '\n\n'
}

export function decodeSeparatorInput(raw: string): string {
  const value = raw.trim()
  if (value.length === 0) return ''
  try {
    const escapedValue = value.replaceAll('"', String.raw`\"`)
    return JSON.parse(`"${escapedValue}"`)
  } catch {
    return value
  }
}

export function encodeSeparatorInput(separator: string): string {
  const text = JSON.stringify(separator)
    .slice(1, -1)
    .replaceAll(String.raw`\"`, '"')
  return text.replace(/^\s+|\s+$/g, (whitespace) =>
    Array.from(whitespace, (character) => `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`).join(''),
  )
}
