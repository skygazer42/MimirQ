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

  it('uses Ocean tokens for the graph canvas, empty state and overlays', () => {
    const canvasSrc = readSource('./graph-canvas.tsx')
    const controlsSrc = readSource('./graph-floating-controls.tsx')
    const headerSrc = readSource('./graph-page-header.tsx')
    const analysisSrc = readSource('./kg-network-analysis-panel.tsx')

    expect(canvasSrc).toContain("backgroundColor: 'hsl(var(--background))'")
    expect(canvasSrc).toContain('const gridOpacity = isDark ? 0.06 : 0.035')
    expect(canvasSrc).toContain('linear-gradient(hsl(var(--info) / ${gridOpacity})')
    expect(canvasSrc).not.toContain("backgroundColor: '#f8faff'")
    expect(canvasSrc).not.toContain("backgroundColor: '#0f1722'")
    expect(canvasSrc).not.toContain('rgba(139, 92, 246')
    expect(canvasSrc).not.toContain('radial-gradient(circle at')
    expect(canvasSrc).toContain('fill="hsl(var(--info) / 0.10)"')
    expect(canvasSrc).toContain(
      'h-9 gap-1.5 rounded-md bg-info px-3.5 text-[12px] font-medium'
    )
    expect(canvasSrc).toContain(
      'text-info-foreground shadow-none hover:bg-info/90'
    )
    expect(canvasSrc).toContain(
      'h-9 gap-1.5 rounded-md border-info/25 bg-background/75 px-3.5 text-[12px] font-medium'
    )
    expect(canvasSrc).not.toContain('size="lg"')
    expect(canvasSrc).toContain(
      'text-foreground shadow-none hover:bg-info/[0.08] hover:text-info'
    )

    expect(analysisSrc).toContain('border-info/15 bg-background/88')
    expect(analysisSrc).toContain(
      'border border-info/20 bg-info/[0.08] text-info'
    )
    expect(analysisSrc).toContain("matchMedia('(max-width: 1279px)')")
    expect(analysisSrc).toContain(
      "narrowViewport.addEventListener('change', collapseForNarrowViewport)"
    )
    expect(analysisSrc).not.toContain('bg-foreground text-info-foreground')

    expect(controlsSrc).toContain('border-info/15 bg-background/88')
    expect(controlsSrc).toContain(
      'bg-info/[0.08] text-info ring-1 ring-info/20'
    )

    expect(headerSrc).toContain(
      'border-info/20 bg-info/[0.06] px-2 py-0.5 text-[10px] font-medium text-info'
    )
    expect(headerSrc).toContain('data-[state=checked]:bg-info')
  })
})
