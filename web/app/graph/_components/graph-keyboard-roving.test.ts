import { describe, expect, it } from 'vitest'

import { getNextKeyboardRovingIndex } from './graph-keyboard-roving'

describe('getNextKeyboardRovingIndex', () => {
  it('starts at the first node when no current focus exists', () => {
    expect(getNextKeyboardRovingIndex(-1, 4, 1)).toBe(0)
  })

  it('wraps to the last node when reverse-tabbing from an empty roving state', () => {
    expect(getNextKeyboardRovingIndex(-1, 4, -1)).toBe(3)
  })

  it('wraps around at both ends of the semantic node list', () => {
    expect(getNextKeyboardRovingIndex(3, 4, 1)).toBe(0)
    expect(getNextKeyboardRovingIndex(0, 4, -1)).toBe(3)
  })
})
