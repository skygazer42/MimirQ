import fs from "node:fs"
import path from "node:path"

import { describe, expect, it } from "vitest"

describe("VectorNebula cluster visual contract", () => {
  it("defines and uses per-cluster visual metadata beyond color", () => {
    const src = fs.readFileSync(path.resolve(__dirname, "vector-nebula.tsx"), "utf8")

    expect(src).toContain("style:")
    expect(src).toContain("spread:")
    expect(src).toContain("sizeRange:")
    expect(src).toContain("halo:")
    expect(src).toContain("shapeLabel:")

    expect(src).toContain("cluster.style.spread")
    expect(src).toContain("node.style.sizeRange")
    expect(src).toContain("node.style.halo")
    expect(src).toContain("c.style.shapeLabel")
    expect(src).toContain("c.style.densityLabel")
  })
})
