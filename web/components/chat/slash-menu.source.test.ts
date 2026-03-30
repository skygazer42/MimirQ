import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('slash menu source', () => {
  it('moves command copy into the SlashMenu catalog', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'slash-menu.tsx'), 'utf8')

    expect(src).toContain("useTranslations('SlashMenu')")
    expect(src).toContain("placeholder={t('placeholder')}")
    expect(src).toContain("label: t(`commands.${id}.label`)")
    expect(src).toContain("keywords: t.raw(`commands.${id}.keywords`) as string[]")
  })
})
