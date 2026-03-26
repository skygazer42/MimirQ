import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('graph page type safety', () => {
  it('extracts graph helper types and removes the most obvious any-based hotspots from the page', () => {
    const page = read('./page.tsx')
    const utils = read('./graph-page-utils.ts')

    expect(page).toContain("from './graph-page-utils'")
    expect(utils).toContain('export type GraphNodeLike')
    expect(utils).toContain('export type GraphLinkLike')
    expect(utils).toContain('export function getGraphNodeKind')
    expect(utils).toContain('export function getGraphLinkEndpointId')
    expect(page).not.toContain("| { type: 'node'; node: any }")
    expect(page).not.toContain("| { type: 'link'; link: any }")
    expect(page).not.toContain('function getGraphNodeKind(node: any)')
    expect(page).not.toContain('function getGraphNodeType(node: any)')
    expect(page).not.toContain('function getGraphLinkKind(link: any)')
    expect(page).not.toContain('function getGraphLinkPredicate(link: any)')
    expect(page).not.toContain('function getGraphLinkConfidence(link: any)')
    expect(page).not.toContain('function getGraphLinkEndpointId(raw: any)')
    expect(page).not.toContain('items.map((d: any)')
    expect(page).not.toContain('items.filter((d: any)')
    expect(page).not.toContain('const nextLinks: any[] = []')
    expect(page).not.toContain('const _extractTraceFromPayload = (payload: any)')
    expect(page).not.toContain('const handleDeleteNode = useCallback((node?: any)')
    expect(page).not.toContain('const finishConnection = (targetNode: any)')
    expect(page).not.toContain('const handleNodeClick = (node: any)')
    expect(page).not.toContain('const handleLinkClick = (link: any)')
    expect(page).not.toContain('(start: any, end: any)')
    expect(page).not.toContain('(node?: any)')
    expect(page).not.toContain('.filter((l: any)')
    expect(page).not.toContain('.map((l: any, idx: number)')
  })

  it('keeps heavy right-side detail panels extracted into dedicated graph components', () => {
    const page = read('./page.tsx')
    const nodePanel = read('./_components/graph-node-detail-panel.tsx')
    const linkPanel = read('./_components/graph-link-detail-panel.tsx')

    expect(page).toContain('GraphNodeDetailPanel')
    expect(page).toContain('GraphLinkDetailPanel')
    expect(nodePanel).toContain('export function GraphNodeDetailPanel')
    expect(linkPanel).toContain('export function GraphLinkDetailPanel')
    expect(page).not.toContain('属性详情')
    expect(page).not.toContain('KG Detail')
    expect(page).not.toContain('Self-loop Group')
  })

  it('keeps graph action dialogs extracted into a dedicated overlay component', () => {
    const page = read('./page.tsx')
    const dialogs = read('./_components/graph-action-dialogs.tsx')

    expect(page).toContain('GraphActionDialogs')
    expect(dialogs).toContain('export function GraphActionDialogs')
    expect(page).not.toContain('删除节点？')
    expect(page).not.toContain('确认合并？')
    expect(page).not.toContain('拆分实体')
    expect(page).not.toContain('关系名称')
  })
})
