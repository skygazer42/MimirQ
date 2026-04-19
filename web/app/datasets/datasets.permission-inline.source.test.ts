import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Datasets inline permission control', () => {
  it('renders an inline permission select and routes partial-members edits through the existing dialog', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../../components/datasets/datasets-page.tsx'), 'utf8')
    expect(src).toContain('handleInspectorPermissionChange')
    expect(src).toContain('value={selectedDataset.permission}')
    expect(src).toContain("openEdit(dataset, 'partial_members')")
    expect(src).toContain('<div className="w-[132px]">')
    expect(src).toContain('ml-auto h-8 w-auto min-w-[88px] max-w-full justify-end')
    expect(src).toContain('[&>svg]:h-3')
    expect(src).toContain('[&>span]:text-right')
    expect(src).toContain('<SelectItem value="only_me">仅自己</SelectItem>')
    expect(src).toContain('<SelectItem value="all_team_members">全员可见</SelectItem>')
    expect(src).toContain('<SelectItem value="partial_members">部分成员</SelectItem>')
  })
})
