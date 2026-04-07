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

  it('exposes embedding diagnostics and local outlier triage controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-workbench.tsx'), 'utf8')

    expect(src).toContain('向量诊断')
    expect(src).toContain('3D 投影预览')
    expect(src).toContain('异常点标注')
    expect(src).toContain('禁用候选')
    expect(src).toContain('标记待审')
  })

  it('shows a compact selected-cell drilldown for clicked heatmap cells', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-workbench.tsx'), 'utf8')

    expect(src).toContain('选中单元')
    expect(src).toContain('点击热力图任意单元后，在这里查看坐标和值。')
    expect(src).toContain('plotly_click')
    expect(src).toContain('当前显示')
  })

  it('supports collapsing the right inspector down to the icon rail', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-workbench.tsx'), 'utf8')

    expect(src).toContain('收起右侧栏')
    expect(src).toContain('展开右侧栏')
    expect(src).toContain('isRightSidebarCollapsed')
  })

  it('supports collapsing the left setup sidebar down to the icon rail', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-workbench.tsx'), 'utf8')

    expect(src).toContain('收起左侧栏')
    expect(src).toContain('展开左侧栏')
    expect(src).toContain('isLeftSidebarCollapsed')
  })

  it('keeps icon-only controls accessible with contextual aria-labels', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-workbench.tsx'), 'utf8')

    expect(src).toContain('aria-label={`将 ${entry.xCollectionLabel} vs ${entry.yCollectionLabel} 设为显示数据矩阵`}')
    expect(src).toContain('aria-label={`将 ${entry.xCollectionLabel} vs ${entry.yCollectionLabel} 的筛选条件加入当前视图`}')
    expect(src).toMatch(
      /aria-label=\{\s*btn\?\.exclusive\s*\?\s*`退出 \$\{entry\.xCollectionLabel\} vs \$\{entry\.yCollectionLabel\} 的独占编辑模式`\s*:\s*`将 \$\{entry\.xCollectionLabel\} vs \$\{entry\.yCollectionLabel\} 设为独占编辑矩阵`\s*\}/
    )
    expect(src).toContain('aria-label={`为${label}添加一个 Collection 选择器`}')
    expect(src).toContain('aria-label={`删除第 ${idx + 1} 个${label}选择器`}')

    expect(src).not.toContain('aria-label="应用数据"')
    expect(src).not.toContain('aria-label="应用筛选器"')
    expect(src).not.toContain('aria-label="独占模式"')
    expect(src).not.toContain('aria-label="添加"')
    expect(src).not.toContain('aria-label="删除"')
  })

  it('uses sidebar-tinted shells for the remaining expert workbench surfaces', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-workbench.tsx'), 'utf8')

    expect(src).toContain('w-12 border-r border-sidebar-border/70 bg-sidebar/90 backdrop-blur-xl')
    expect(src).toContain('relative h-full border-r border-sidebar-border/70 bg-sidebar/78 backdrop-blur-xl flex flex-col')
    expect(src).toContain('rounded-2xl border border-sidebar-border/70 bg-sidebar/60 p-3 shadow-soft')
    expect(src).toContain('rounded-xl border border-sidebar-border/70 bg-sidebar/55 p-4 shadow-soft')
    expect(src).toContain("rounded-xl border border-sidebar-border/70 bg-sidebar/55', compact ? 'p-3' : 'p-4'")
  })
})
