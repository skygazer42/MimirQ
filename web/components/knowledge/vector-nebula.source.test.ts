import fs from "node:fs"
import path from "node:path"

import { describe, expect, it } from "vitest"

describe("VectorNebula cluster visual contract", () => {
  it("uses real backend documents and chunks instead of mock nebula data", () => {
    const src = fs.readFileSync(path.resolve(__dirname, "vector-nebula.tsx"), "utf8")

    expect(src).toContain("from \"@tanstack/react-query\"")
    expect(src).toContain("useQuery")
    expect(src).toContain("queryKey: queryKeys.documents.nebula")
    expect(src).toContain("documentApi.list")
    expect(src).toContain("documentApi.listChunks")
    expect(src).toContain("buildNebula(documents, chunksByDocument)")
    expect(src).toContain("来源：/documents 与 /documents/:id/chunks")
    expect(src).not.toContain("generateMockData")
    expect(src).not.toContain("mock-doc-id")
    expect(src).not.toContain("const [data, setData]")
    expect(src).not.toContain("setLoading")
    expect(src).not.toContain("setError")
    expect(src.split("documentApi.list({ limit: 24").length - 1).toBe(1)
  })

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
    expect(src).toContain("cluster.style.shapeLabel")
    expect(src).toContain("cluster.style.densityLabel")
  })

  it("filters the known upstream Three Clock deprecation without hiding other warnings", () => {
    const src = fs.readFileSync(path.resolve(__dirname, "vector-nebula.tsx"), "utf8")

    expect(src).toContain("THREE_CLOCK_DEPRECATION_WARNING")
    expect(src).toContain("isThreeClockDeprecationWarning(args)")
    expect(src).toContain("withSuppressedThreeClockWarning")
    expect(src).toContain("originalWarn(...args)")
  })
})
