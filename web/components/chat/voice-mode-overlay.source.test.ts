import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('VoiceModeOverlay accessibility', () => {
  it('marks the waveform canvas as decorative without presentation role hacks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'voice-mode-overlay.tsx'), 'utf8')

    expect(src).toContain('aria-hidden="true"')
    expect(src).not.toContain('role="presentation"')
  })
})
