// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readSource(relativePath: string) {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('graph surfaces stay crisp', () => {
  it('avoids blurred floating shells for graph overlays and controls', () => {
    const controlsSrc = readSource('./graph-floating-controls.tsx')
    const explainSrc = readSource('./graph-explainability-panel.tsx')
    const linkDetailSrc = readSource('./graph-link-detail-panel.tsx')
    const contextMenuSrc = readSource('./graph-context-menu.tsx')
    const headerSrc = readSource('./graph-page-header.tsx')
    const analysisSrc = readSource('./kg-network-analysis-panel.tsx')

    expect(controlsSrc).not.toContain('backdrop-blur')
    expect(controlsSrc).not.toContain('shadow-soft')

    expect(explainSrc).not.toContain('shadow-strong')
    expect(linkDetailSrc).not.toContain('shadow-strong')
    expect(contextMenuSrc).not.toContain('backdrop-blur')
    expect(contextMenuSrc).not.toContain('shadow-strong')
    expect(headerSrc).not.toContain('backdrop-blur')

    expect(analysisSrc).not.toContain('backdrop-blur')
    expect(analysisSrc).not.toContain('shadow-soft')
  })

  it('removes decorative blur layers from graph detail surfaces', () => {
    const nodeDetailSrc = readSource('./graph-node-detail-panel.tsx')
    const canvasSrc = readSource('./graph-canvas.tsx')

    expect(nodeDetailSrc).not.toContain('bg-[radial-gradient(')
    expect(nodeDetailSrc).not.toContain('backdrop-blur')
    expect(nodeDetailSrc).not.toContain('shadow-[12px_17px_51px_hsl(var(--foreground)/0.16)]')
    expect(nodeDetailSrc).not.toContain('shadow-[12px_17px_51px_hsl(var(--foreground)/0.18)]')

    expect(canvasSrc).not.toContain('backdrop-blur')
    expect(canvasSrc).not.toContain('shadow-soft')
    expect(canvasSrc).not.toContain('shadow-[12px_18px_46px_-28px_rgba(15,23,42,0.44)]')
    expect(canvasSrc).not.toContain('shadow-[12px_18px_42px_-24px_rgba(15,23,42,0.38)]')
    expect(canvasSrc).not.toContain(
      'bg-[radial-gradient(circle_at_center,transparent_52%,hsl(var(--info)/0.025)_100%)]'
    )
  })
})
