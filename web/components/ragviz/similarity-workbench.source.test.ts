import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('similarity workbench source', () => {
  it('shows branded loading states for lazily loaded Plotly heatmaps', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-workbench.tsx'), 'utf8')

    expect(src).toContain('PageLoading')
    expect(src).toContain('正在加载相似度热力图...')
    expect(src).toContain('正在初始化图表引擎...')
  })
})
