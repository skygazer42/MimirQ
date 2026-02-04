import fs from "node:fs"
import path from "node:path"
import { describe, expect, it } from "vitest"

describe("SearchInput", () => {
  it('uses a non-primary clear affordance (IconButton variant="ghost")', () => {
    const src = fs.readFileSync(path.resolve(__dirname, "search-input.tsx"), "utf8")
    expect(src).toContain('variant="ghost"')
  })
})

