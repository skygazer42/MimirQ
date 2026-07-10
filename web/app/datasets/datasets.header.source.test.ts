import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Datasets page header', () => {
  it('does not use decorative pulse animations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../components/datasets/datasets-page.tsx'), 'utf8')
    expect(src).not.toContain('animate-pulse')
  })

  it('uses the dedicated create dataset CTA for the header action only', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../components/datasets/datasets-page.tsx'), 'utf8')
    expect(src).toContain("import { CreateDatasetButton } from '@/components/datasets/create-dataset-button'")
    expect(src.match(/<CreateDatasetButton\b/g) ?? []).toHaveLength(1)
  })

  it('keeps the hero shell aligned with the knowledge workbench look', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../components/datasets/datasets-page.tsx'), 'utf8')

    expect(src).toContain('rounded-3xl border border-sky-200/60 bg-gradient-to-br from-white via-sky-50/40 to-blue-50/30')
    expect(src).toContain('shadow-xl shadow-sky-200/30 backdrop-blur-xl')
    expect(src).toContain('text-[26px] font-black tracking-tight text-slate-900')
    expect(src).toContain('text-[13px] font-semibold leading-5 text-sky-600/90')
  })

  it('renders the CTA as a clean solid button with a Plus icon', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../components/datasets/create-dataset-button.tsx'), 'utf8')
    expect(src).toContain("from 'lucide-react'")
    expect(src).toContain('<Plus')
    expect(src).toContain('rounded-full')
    expect(src).not.toContain('bg-[#006aff]')
    expect(src).not.toContain('border-[6px]')
  })
})
