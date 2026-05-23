'use client'

import type { Dispatch, RefObject, SetStateAction } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { toast } from 'sonner'

import { useRouter } from '@/i18n/navigation'
import { kgApi } from '@/lib/api/graph'
import { sanitizeFilename } from '@/lib/sanitize'

import {
  coerceTrimmedString,
  getGraphNodeKind,
  type GraphContextMenuState,
  type GraphContextMenuTarget,
  type GraphLinkLike,
  type GraphNodeLike,
  stripFilenameExtension,
} from './graph-page-utils'

type GraphViewportApi = {
  zoomToFit?: () => void
  exportPngDataUrl?: () => string | null
  exportSvgString?: () => string | null
} | null

type GraphScopeParams = Readonly<{
  document_ids?: string[]
  dataset_id?: string
  pipeline_hash?: string
}> | null

type DeleteNodeTarget = {
  id: string
  label: string
} | null

function getGraphNodeDocumentId(node: GraphNodeLike | null | undefined): string {
  return coerceTrimmedString(node?.meta?.document_id ?? node?.source)
}

export function buildGraphNodeChatPrompt(node: GraphNodeLike | null | undefined): string {
  const label = coerceTrimmedString(node?.label ?? node?.id)
  if (!label) return ''

  const documentId = getGraphNodeDocumentId(node)
  if (documentId) {
    return `请总结一下该文档的核心观点，并结合图谱节点「${label}」提炼关键证据与后续问题。源文档 ID: ${documentId}。`
  }

  const nodeKind = getGraphNodeKind(node)
  if (nodeKind === 'entity') {
    return `请围绕图谱节点「${label}」总结核心观点、关联事件、关键关系与后续核查线索。`
  }
  if (nodeKind === 'event') {
    return `请围绕图谱事件「${label}」总结背景、涉及实体、关键证据与后续影响。`
  }

  return `请围绕图谱节点「${label}」总结关键信息、上下文关系与下一步建议。`
}

type UseGraphPageActionsParams = Readonly<{
  graphViewportRef: RefObject<HTMLDivElement | null>
  getActiveGraph: () => GraphViewportApi
  selectedNode: GraphNodeLike | null
  fileName: string | null
  viewMode: '2d' | '3d'
  datasetId: string | null
  dataSource: 'live' | 'file'
  scopeParams: GraphScopeParams
  includeEntityLinks: boolean
  includeRelationLinks: boolean
  minSharedEvents: number
  maxEntityLinks: number
  setIsLoading: Dispatch<SetStateAction<boolean>>
  setIsDetailOpen: Dispatch<SetStateAction<boolean>>
  setIsLinkDetailOpen: Dispatch<SetStateAction<boolean>>
  setSelectedNode: Dispatch<SetStateAction<GraphNodeLike | null>>
  setSelectedLink: Dispatch<SetStateAction<GraphLinkLike | null>>
  setDeleteNodeOpen: Dispatch<SetStateAction<boolean>>
  setDeleteNodeTarget: Dispatch<SetStateAction<DeleteNodeTarget>>
}>

export function useGraphPageActions({
  graphViewportRef,
  getActiveGraph,
  selectedNode,
  fileName,
  viewMode,
  datasetId,
  dataSource,
  scopeParams,
  includeEntityLinks,
  includeRelationLinks,
  minSharedEvents,
  maxEntityLinks,
  setIsLoading,
  setIsDetailOpen,
  setIsLinkDetailOpen,
  setSelectedNode,
  setSelectedLink,
  setDeleteNodeOpen,
  setDeleteNodeTarget,
}: UseGraphPageActionsParams) {
  const router = useRouter()
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [contextMenu, setContextMenu] = useState<GraphContextMenuState | null>(null)
  const [exportOpen, setExportOpen] = useState(false)

  const closeContextMenu = useCallback(() => {
    setContextMenu(null)
  }, [])

  const openContextMenu = useCallback(
    (event: MouseEvent, target: GraphContextMenuTarget) => {
      try {
        event.preventDefault?.()
        event.stopPropagation?.()
      } catch {}

      const rect = graphViewportRef.current?.getBoundingClientRect()
      if (!rect) return

      const menuWidth = 272
      const menuHeight = 320
      const padding = 12
      let x = event.clientX - rect.left
      let y = event.clientY - rect.top
      x = Math.max(padding, Math.min(x, rect.width - menuWidth - padding))
      y = Math.max(padding, Math.min(y, rect.height - menuHeight - padding))
      setContextMenu({ x, y, target })
    },
    [graphViewportRef]
  )

  useEffect(() => {
    if (!contextMenu) return
    const dismiss = () => setContextMenu(null)
    globalThis.window.addEventListener('mousedown', dismiss)
    globalThis.window.addEventListener('scroll', dismiss, true)
    return () => {
      globalThis.window.removeEventListener('mousedown', dismiss)
      globalThis.window.removeEventListener('scroll', dismiss, true)
    }
  }, [contextMenu])

  useEffect(() => {
    if (typeof document === 'undefined') return
    const syncFullscreen = () => {
      setIsFullscreen(Boolean(document.fullscreenElement))
    }
    syncFullscreen()
    document.addEventListener('fullscreenchange', syncFullscreen)
    return () => document.removeEventListener('fullscreenchange', syncFullscreen)
  }, [])

  const toggleFullscreen = useCallback(async () => {
    if (typeof document === 'undefined') return
    try {
      if (!document.fullscreenElement) {
        await graphViewportRef.current?.requestFullscreen?.()
      } else {
        await document.exitFullscreen?.()
      }
    } catch {
      toast.error('全屏切换失败')
    }
  }, [graphViewportRef])

  const handleToggleFullscreen = useCallback(() => {
    void toggleFullscreen()
  }, [toggleFullscreen])

  const handleBackgroundClick = useCallback(() => {
    setIsDetailOpen(false)
    setIsLinkDetailOpen(false)
    setSelectedLink(null)
    closeContextMenu()
  }, [closeContextMenu, setIsDetailOpen, setIsLinkDetailOpen, setSelectedLink])

  const handleNodeRightClick = useCallback(
    (node: GraphNodeLike, event: MouseEvent) => {
      setSelectedNode(node)
      setSelectedLink(null)
      setIsDetailOpen(false)
      setIsLinkDetailOpen(false)
      openContextMenu(event, { type: 'node', node })
    },
    [openContextMenu, setIsDetailOpen, setIsLinkDetailOpen, setSelectedLink, setSelectedNode]
  )

  const handleLinkRightClick = useCallback(
    (link: GraphLinkLike, event: MouseEvent) => {
      setSelectedLink(link)
      setSelectedNode(null)
      setIsDetailOpen(false)
      setIsLinkDetailOpen(false)
      openContextMenu(event, { type: 'link', link })
    },
    [openContextMenu, setIsDetailOpen, setIsLinkDetailOpen, setSelectedLink, setSelectedNode]
  )

  const handleBackgroundRightClick = useCallback(
    (event: MouseEvent) => {
      setIsDetailOpen(false)
      setIsLinkDetailOpen(false)
      openContextMenu(event, { type: 'background' })
    },
    [openContextMenu, setIsDetailOpen, setIsLinkDetailOpen]
  )

  const copyToClipboard = useCallback(async (text: string, label: string) => {
    const value = String(text || '').trim()
    if (!value) {
      toast.error('无可复制内容')
      return
    }

    try {
      if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
        throw new Error('Clipboard API unavailable')
      }
      await navigator.clipboard.writeText(value)
      toast.success(`已复制 ${label}`)
    } catch (error) {
      console.error('clipboard.writeText failed:', error)
      toast.error('复制失败（浏览器权限限制）')
    }
  }, [])

  const handleCopyNodeId = useCallback(
    (nodeId: string) => {
      void copyToClipboard(nodeId, '节点 ID')
    },
    [copyToClipboard]
  )

  const handleCopyLinkPredicate = useCallback(
    (predicate: string) => {
      void copyToClipboard(predicate, 'Predicate')
    },
    [copyToClipboard]
  )

  const chatWithNode = useCallback(
    (node?: GraphNodeLike) => {
      const target = node ?? selectedNode
      const prompt = buildGraphNodeChatPrompt(target)
      if (!prompt) return
      const params = new URLSearchParams({
        prompt,
        autorun: '1',
      })
      router.push(`/?${params.toString()}`)
    },
    [router, selectedNode]
  )

  const handleChatWithNode = useCallback(() => {
    chatWithNode()
  }, [chatWithNode])

  const viewSourceForNode = useCallback(
    (node?: GraphNodeLike) => {
      const target = node ?? selectedNode
      const documentId = target?.meta?.document_id || target?.source
      if (documentId) {
        toast(`源文档：${documentId}`)
        return
      }
      toast('未找到源文档信息')
    },
    [selectedNode]
  )

  const handleViewSource = useCallback(() => {
    viewSourceForNode()
  }, [viewSourceForNode])

  const exportBaseName = useMemo(() => {
    const base =
      stripFilenameExtension(fileName || '') ||
      (datasetId ? `dataset-${datasetId}` : '') ||
      'mimirq-kg'
    return sanitizeFilename(`${base}-${viewMode}`)
  }, [datasetId, fileName, viewMode])

  const exportGraph = useCallback(
    async (format: 'png' | 'svg', mode: 'download' | 'copy') => {
      const api = getActiveGraph()
      if (!api) {
        toast.error('图谱尚未就绪')
        return
      }

      if (format === 'png') {
        const dataUrl = api.exportPngDataUrl?.()
        if (!dataUrl) {
          toast.error('导出 PNG 失败')
          return
        }
        if (mode === 'copy') {
          await copyToClipboard(dataUrl, 'PNG DataURL')
          return
        }
        const anchor = document.createElement('a')
        anchor.href = dataUrl
        anchor.download = `${exportBaseName}.png`
        anchor.click()
        toast.success('已导出 PNG')
        return
      }

      const svg = api.exportSvgString?.()
      if (!svg) {
        toast.error('导出 SVG 失败')
        return
      }
      if (mode === 'copy') {
        await copyToClipboard(svg, 'SVG')
        return
      }

      const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${exportBaseName}.svg`
      anchor.click()
      globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
      toast.success('已导出 SVG')
    },
    [copyToClipboard, exportBaseName, getActiveGraph]
  )

  const handleExportPngDownload = useCallback(() => {
    setExportOpen(false)
    void exportGraph('png', 'download')
  }, [exportGraph])

  const handleExportSvgDownload = useCallback(() => {
    setExportOpen(false)
    void exportGraph('svg', 'download')
  }, [exportGraph])

  const handleExportPngCopy = useCallback(() => {
    setExportOpen(false)
    void exportGraph('png', 'copy')
  }, [exportGraph])

  const handleExportSvgCopy = useCallback(() => {
    setExportOpen(false)
    void exportGraph('svg', 'copy')
  }, [exportGraph])

  const handleExportGraphML = useCallback(async () => {
    if (dataSource !== 'live') {
      toast.info('仅支持导出后端 KG 实时图谱')
      return
    }

    setIsLoading(true)
    try {
      const xml = await kgApi.exportGraphML({
        document_ids: scopeParams?.document_ids,
        dataset_id: scopeParams?.dataset_id,
        pipeline_hash: scopeParams?.pipeline_hash,
        include_entity_links: includeEntityLinks,
        include_relation_links: includeRelationLinks,
        min_shared_events: minSharedEvents,
        max_entity_links: maxEntityLinks,
      })
      const blob = new Blob([xml], { type: 'application/graphml+xml;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'mimirq-kg.graphml'
      anchor.click()
      URL.revokeObjectURL(url)
      toast.success('已导出 GraphML')
    } catch (error) {
      console.error('Export GraphML failed:', error)
      toast.error('导出 GraphML 失败')
    } finally {
      setIsLoading(false)
    }
  }, [
    dataSource,
    includeEntityLinks,
    includeRelationLinks,
    maxEntityLinks,
    minSharedEvents,
    scopeParams,
    setIsLoading,
  ])

  const handleDeleteNodeOpenChange = useCallback(
    (open: boolean) => {
      setDeleteNodeOpen(open)
      if (!open) setDeleteNodeTarget(null)
    },
    [setDeleteNodeOpen, setDeleteNodeTarget]
  )

  return {
    isFullscreen,
    contextMenu,
    exportOpen,
    setExportOpen,
    closeContextMenu,
    handleBackgroundClick,
    handleNodeRightClick,
    handleLinkRightClick,
    handleBackgroundRightClick,
    handleToggleFullscreen,
    handleCopyNodeId,
    handleCopyLinkPredicate,
    chatWithNode,
    handleChatWithNode,
    viewSourceForNode,
    handleViewSource,
    handleExportPngDownload,
    handleExportSvgDownload,
    handleExportPngCopy,
    handleExportSvgCopy,
    handleExportGraphML,
    handleDeleteNodeOpenChange,
  }
}

export type UseGraphPageActionsResult = ReturnType<typeof useGraphPageActions>
