import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('data cleaner source style', () => {
  it('uses light semantic action surfaces for clean and LLM controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'data-cleaner.tsx'), 'utf8')

    expect(src).not.toContain('Button onClick={handleApply} disabled={isApplying} className="h-8 flex-1 gap-2 rounded-lg shadow-none"')
    expect(src).not.toContain("variant={llmEnabled ? 'default' : 'outline'}")
    expect(src).not.toContain('border-primary/25 bg-primary/10 text-primary')
    expect(src).toContain('from-primary/[0.16] via-primary/[0.12] to-info/[0.14]')
    expect(src).toContain('shadow-[0_8px_18px_rgba(37,99,235,0.08)]')
    expect(src).toContain('border-accent/20 bg-accent/5')
    expect(src).toContain('border-accent/30 bg-accent/10 text-accent')
  })

  it('gives the cleaning config area a calmer workbench hierarchy', () => {
    const cleanerSrc = fs.readFileSync(path.resolve(__dirname, 'data-cleaner.tsx'), 'utf8')
    const profileSrc = fs.readFileSync(path.resolve(__dirname, '../governance-profile-selector.tsx'), 'utf8')
    const pipelineSrc = fs.readFileSync(path.resolve(__dirname, '../pipeline-options-panel.tsx'), 'utf8')

    expect(cleanerSrc).toContain('const configHeaderClass =')
    expect(cleanerSrc).toContain('from-info/10 via-card to-primary/5')
    expect(cleanerSrc).toContain('const rulesPanelClass =')
    expect(cleanerSrc).toContain('border-info/15 bg-gradient-to-b from-surface-2/80 to-card/95')
    expect(profileSrc).toContain('const primaryActionClass =')
    expect(profileSrc).toContain('border-primary/25 bg-primary/10 text-primary')
    expect(pipelineSrc).toContain('const toggleCardClass =')
    expect(pipelineSrc).toContain('border-primary/15 bg-primary/5')
    expect(pipelineSrc).toContain('const indexPresetCardClass =')
    expect(pipelineSrc).toContain('border-info/15 bg-info/5')
    expect(pipelineSrc).not.toContain('text-muted-foreground italic')
    expect(pipelineSrc).toContain('text-[11px] leading-snug text-muted-foreground/75')
    expect(pipelineSrc).toContain('compact && "px-2.5 py-1.5 text-[10px]"')
  })

  it('keeps the smart cleaning configuration compact and non-repetitive', () => {
    const cleanerSrc = fs.readFileSync(path.resolve(__dirname, 'data-cleaner.tsx'), 'utf8')
    const pipelineSrc = fs.readFileSync(path.resolve(__dirname, '../pipeline-options-panel.tsx'), 'utf8')

    expect(cleanerSrc).toContain('const configShellClass =')
    expect(cleanerSrc).toContain('PipelineOptionsPanel compact={true}')
    expect(cleanerSrc).not.toContain('预设 / 管线 / 索引模式')
    expect(cleanerSrc).toContain('const llmPanelClass =')
    expect(cleanerSrc).toContain('const diffPanelClass =')
    expect(pipelineSrc).toContain('const pipelinePanelClass = cn(')
    expect(pipelineSrc).toContain('compact ? "space-y-2.5 font-sans" : "space-y-3.5 font-sans"')
    expect(pipelineSrc).toContain('compact ? "flex items-center justify-between gap-1.5')
  })
})
