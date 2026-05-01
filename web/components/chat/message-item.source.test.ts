import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('message item source', () => {
  it('uses semantic citation buttons and avoids deprecated clipboard fallbacks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).not.toContain('document.execCommand(')
    expect(src).not.toContain('document.body.removeChild(')
    expect(src).not.toContain('maybeAttachImageAuthToken')
    expect(src).not.toContain("searchParams.set('token'")
    expect(src).not.toContain("searchParams.set('access_token'")
    expect(src).not.toContain('role="button"')
    expect(src).toContain("toast.error('复制失败，请检查浏览器剪贴板权限')")
    expect(src).toContain('confidence_score')
    expect(src).toContain('来源速览')
    expect(src).toContain('来源与证据')
    expect(src).toContain('INLINE_CITATION_HREF_PREFIX')
    expect(src).toContain('AuthImage')
    expect(src).toContain('handleInlineCitationClick')
    expect(src).toContain('sanitizeMarkdownHref')
    expect(src).toContain('resolveMarkdownImageSrc')
    expect(src).toContain('skipHtml')
    expect(src).toContain('function getConfidenceMeta(')
    expect(src).toContain('function formatMetricValue(')
    expect(src).toContain('followup_questions')
    expect(src).toContain('继续追问')
    expect(src).toContain('反馈评分')
    expect(src).toContain('text-primary-foreground [&>*]:text-inherit')
    expect(src).toContain('prose prose-neutral dark:prose-invert')
    expect(src).toContain('prose-code:font-mono')
    expect(src).toContain('prose-code:text-primary')
  })

  it('prefetches document evidence on citation hover before opening the viewer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).toContain('prefetchDocumentView')
    expect(src).toContain('const handlePrefetch = useCallback')
    expect(src).toContain('const handleInlineCitationPrefetch = useCallback')
    expect(src).toContain('const handlePreview = useCallback')
    expect(src).toContain('onMouseEnter={handlePreview}')
    expect(src).toContain('onFocus={handlePreview}')
    expect(src).toContain('handleInlineCitationPrefetch(href)')
  })

  it('opens cited documents into the preview tab when hovering inline citations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).toContain('const handlePreviewCitation = useCallback')
    expect(src).toContain("activeTab: 'preview'")
    expect(src).toContain('onMouseEnter={() => handlePreviewCitation(href)}')
    expect(src).toContain('onFocus={() => handlePreviewCitation(href)}')
    expect(src).toContain('previewAnchor: getDocumentPreviewAnchorFromCitation(citation)')
  })

  it('uses reduced-motion-safe layout transitions for streaming assistant cards and step updates', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).toContain("from 'framer-motion'")
    expect(src).toContain('useReducedMotion')
    expect(src).toContain('AnimatePresence')
    expect(src).toContain('layout={!reduceMotion && isStreaming}')
    expect(src).toContain('transition={streamingLayoutTransition}')
  })

  it('collapses assistant thinking steps behind an accessible disclosure', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).toContain('const [stepsOpen, setStepsOpen] = useState(() => isStreaming)')
    expect(src).toContain('aria-expanded={stepsOpen}')
    expect(src).toContain('setStepsOpen((open) => !open)')
    expect(src).toContain('{message.steps.length} 步')
    expect(src).toContain('stepsOpen ? (')
    expect(src).toContain('思考路径')
  })

  it('exposes expert-loop actions after feedback is captured', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).toContain('feedbackApi.toRegressionCase(')
    expect(src).toContain('documentApi.get(')
    expect(src).toContain('送入证据库')
    expect(src).toContain('转为回归用例')
    expect(src).toContain('/evidence?feedback_id=')
  })
})
