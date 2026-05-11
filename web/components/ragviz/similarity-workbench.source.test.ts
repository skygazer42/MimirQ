import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('similarity workbench source', () => {
  it('shows branded loading states for lazily loaded Plotly heatmaps', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'similarity-workbench.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'PageLoading')
    expectSourceToContain(src, '正在加载相似度热力图...')
    expectSourceToContain(src, '正在初始化图表引擎...')
  })

  it('exposes embedding diagnostics and local outlier triage controls', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'similarity-workbench.tsx'),
      'utf8'
    )

    expectSourceToContain(src, '向量诊断')
    expectSourceToContain(src, '3D 投影预览')
    expectSourceToContain(src, '异常点标注')
    expectSourceToContain(src, '禁用候选')
    expectSourceToContain(src, '标记待审')
  })

  it('shows a compact selected-cell drilldown for clicked heatmap cells', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'similarity-workbench.tsx'),
      'utf8'
    )

    expectSourceToContain(src, '选中单元')
    expectSourceToContain(
      src,
      '点击热力图任意单元后，在这里查看坐标、相似度和 Top 相关项。'
    )
    expectSourceToContain(src, 'Top 相关')
    expectSourceToContain(src, 'plotly_click')
    expectSourceToContain(src, '当前显示')
  })

  it('supports collapsing the right inspector down to the icon rail', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'similarity-workbench.tsx'),
      'utf8'
    )

    expectSourceToContain(src, '收起右侧栏')
    expectSourceToContain(src, '展开右侧栏')
    expectSourceToContain(src, 'isRightSidebarCollapsed')
  })

  it('supports collapsing the left setup sidebar down to the icon rail', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'similarity-workbench.tsx'),
      'utf8'
    )

    expectSourceToContain(src, '收起左侧栏')
    expectSourceToContain(src, '展开左侧栏')
    expectSourceToContain(src, 'isLeftSidebarCollapsed')
  })

  it('keeps icon-only controls accessible with contextual aria-labels', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'similarity-workbench.tsx'),
      'utf8'
    )

    expectSourceToContain(
      src,
      'aria-label={`将 ${entry.xCollectionLabel} vs ${entry.yCollectionLabel} 设为显示数据矩阵`}'
    )
    expectSourceToContain(
      src,
      'aria-label={`将 ${entry.xCollectionLabel} vs ${entry.yCollectionLabel} 的筛选条件加入当前视图`}'
    )
    expect(src).toMatch(
      /aria-label=\{\s*btn\?\.exclusive\s*\?\s*`退出 \$\{entry\.xCollectionLabel\} vs \$\{entry\.yCollectionLabel\} 的独占编辑模式`\s*:\s*`将 \$\{entry\.xCollectionLabel\} vs \$\{entry\.yCollectionLabel\} 设为独占编辑矩阵`\s*\}/
    )
    expectSourceToContain(
      src,
      'aria-label={`为${label}添加一个 Collection 选择器`}'
    )
    expectSourceToContain(
      src,
      'aria-label={`删除第 ${idx + 1} 个${label}选择器`}'
    )

    expectSourceNotToContain(src, 'aria-label="应用数据"')
    expectSourceNotToContain(src, 'aria-label="应用筛选器"')
    expectSourceNotToContain(src, 'aria-label="独占模式"')
    expectSourceNotToContain(src, 'aria-label="添加"')
    expectSourceNotToContain(src, 'aria-label="删除"')
  })

  it('uses token-based muted shells for the expert workbench surfaces', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'similarity-workbench.tsx'),
      'utf8'
    )

    expectSourceToContain(
      src,
      'flex w-12 flex-col items-center border-r border-sidebar-border/70 bg-background/82 py-2'
    )
    expectSourceToContain(
      src,
      'relative flex h-full flex-col overflow-hidden border-r border-sidebar-border/70 bg-background/78'
    )
    expectSourceToContain(
      src,
      'rounded-[28px] border border-sidebar-border/70 bg-card shadow-soft'
    )
    expectSourceToContain(
      src,
      'rounded-2xl border border-sidebar-border/70 bg-card p-3 shadow-soft'
    )
    expectSourceToContain(
      src,
      "rounded-xl border border-sidebar-border/70 bg-muted/40', compact ? 'p-3' : 'p-4'"
    )
  })

  it('loads similarity collections through TanStack Query', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'similarity-workbench.tsx'),
      'utf8'
    )

    expectSourceToContain(src, "from '@tanstack/react-query'")
    expectSourceToContain(src, 'useQuery')
    expectSourceToContain(src, 'queryKey: queryKeys.ragviz.similarityCollections')
    expectSourceNotToContain(src, 'const [collections, setCollections]')
    expectSourceNotToContain(src, 'setCollectionsLoading')
    expectSourceNotToContain(src, 'setCollectionsError')
    expectSourceNotToContain(src, 'detachPromise(loadCollections())')
  })
})
