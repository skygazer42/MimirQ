import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('command menu source', () => {
  it('moves command-menu copy into the CommandMenu catalog', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain("import { useTranslations } from 'next-intl'")
    expect(src).toContain("const t = useTranslations('CommandMenu')")
    expect(src).toContain("buildCurrentViewPrompt(pathname || '/', t)")
    expect(src).toContain("placeholder={t('search.placeholder')}")
    expect(src).toContain("<CommandEmpty>{t('search.empty')}</CommandEmpty>")
    expect(src).toContain("heading={t('groups.slash')}")
    expect(src).toContain("heading={t('groups.navigation')}")
    expect(src).toContain("heading={t('groups.theme')}")
    expect(src).toContain("label: t(`slash.commands.${id}.label`)")
    expect(src).toContain("keywords: t.raw(`slash.commands.${id}.keywords`) as string[]")
    expect(src).toContain("label: t(`modules.${id}.label`)")
    expect(src).toContain("keywords: t.raw(`modules.${id}.keywords`) as string[]")
  })

  it('uses locale-aware navigation helpers and has wrappers for its remaining route targets', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')
    const webRoot = path.resolve(__dirname, '..')

    expect(src).toContain('usePathname, useRouter')
    expect(src).toContain('@/i18n/navigation')
    expect(src).not.toContain('from "next/navigation"')

    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/observability/page.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/datasets/[id]/profile/page.tsx'))).toBe(true)
  })

  it('supports slash commands and current-view analysis handoff', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain('const isSlashMode = trimmedQuery.startsWith("/")')
    expect(src).toContain("heading={t('groups.slash')}")
    expect(src).toContain('shortcut: "/report"')
    expect(src).toContain('shortcut: "/resume"')
    expect(src).toContain('shortcut: "/upload"')
    expect(src).toContain('shortcut: "/analyze"')
    expect(src).toContain('shortcut: "/stats"')
    expect(src).toContain('shortcut: "/datasets"')
    expect(src).toContain('shortcut: "/history"')
    expect(src).toContain('shortcut: "/parsing"')
    expect(src).toContain('shortcut: "/reports"')
    expect(src).toContain('shortcut: "/observability"')
    expect(src).toContain('shortcut: "/governance"')
    expect(src).toContain('shortcut: "/access"')
    expect(src).toContain('shortcut: "/retry-failed"')
    expect(src).toContain('shortcut: "/pause-active"')
    expect(src).not.toContain('shortcut: "/demo"')
    expect(src).toContain('shortcut: "/precheck"')
    expect(src).toContain('router.push("/usage")')
    expect(src).toContain('router.push("/datasets")')
    expect(src).toContain('router.push("/history")')
    expect(src).toContain('router.push("/parsing")')
    expect(src).toContain('router.push("/reports")')
    expect(src).toContain('router.push("/observability")')
    expect(src).toContain('router.push("/data-governance")')
    expect(src).toContain('router.push("/access-review")')
    expect(src).toContain("globalEventBus.emit('ingestion:retry-all-failed'")
    expect(src).toContain("globalEventBus.emit('ingestion:cancel-all-active'")
    expect(src).not.toContain("globalEventBus.emit('ingestion:toggle-demo-mode'")
    expect(src).toContain("globalEventBus.emit('ingestion:open-precheck'")
    expect(src).toContain("globalEventBus.emit('ingestion:download-report'")
    expect(src).toContain('autorun: "1"')
    expect(src).toContain('buildCurrentViewPrompt(')
  })

  it('defines a chord-based power-user navigation layer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain('e.key === "?"')
    expect(src).toContain('key: "g d"')
    expect(src).toContain('key: "g c"')
    expect(src).toContain('key: "g g"')
    expect(src).toContain('key: "g o"')
    expect(src).toContain('key: "g v"')
    expect(src).toContain('key: "f s"')
    expect(src).toContain('router.push("/knowledge")')
    expect(src).toContain('router.push("/graph")')
    expect(src).toContain('router.push("/observability")')
    expect(src).toContain('router.push("/chunk-preview")')
    expect(src).toContain('resumeLastDocumentContext')
    expect(src).toContain('t("header.hint")')
    expect(src).toContain("heading={t('groups.shortcutMap')}")
    expect(src).toContain('shortcut: "⌘K / Ctrl+K"')
    expect(src).toContain('shortcut: "h / l"')
    expect(src).toContain('shortcut: "← / →"')
    expect(src).toContain('shortcut: "j / k"')
    expect(src).toContain('t("shortcutGuide.stagePrevNext.description")')
  })

  it('expands typed search beyond documents into datasets and conversations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain('datasetApi.list')
    expect(src).toContain('chatApi.listConversations')
    expect(src).toContain('moduleWorkbenchResults')
    expect(src).toContain("heading={t('groups.modules')}")
    expect(src).toContain('keywords: t.raw(`modules.${id}.keywords`) as string[]')
    expect(src).toContain('router.push("/knowledge")')
    expect(src).toContain('router.push("/graph")')
    expect(src).toContain('router.push("/chunk-preview")')
    expect(src).toContain('router.push("/reports")')
    expect(src).toContain('router.push("/observability")')
    expect(src).toContain('router.push("/data-governance")')
    expect(src).toContain('router.push("/access-review")')
    expect(src).toContain("heading={t('groups.datasets')}")
    expect(src).toContain("heading={t('groups.conversations')}")
    expect(src).toContain('router.push(`/datasets/${dataset.id}/profile`)')
    expect(src).toContain('router.push(`/history?id=${conversation.id}`)')
  })

  it('loads typed search results through TanStack Query instead of effect-owned state', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain("import { useQuery } from '@tanstack/react-query'")
    expect(src).toContain("import { queryKeys } from '@/lib/query-keys'")
    expect(src).toContain('queryKey: queryKeys.documents.list')
    expect(src).toContain('queryKey: queryKeys.datasets.list')
    expect(src).toContain('queryKey: queryKeys.chat.conversations')
    expect(src).not.toContain('const [docResults')
    expect(src).not.toContain('const [datasetResults')
    expect(src).not.toContain('const [conversationResults')
    expect(src).not.toContain('requestSeqRef')
    expect(src).not.toContain('Promise.allSettled')
  })

  it('offers a natural-language command handoff for non-slash typed queries', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain("heading={t('groups.aiActions')}")
    expect(src).toContain('t("aiAction.label")')
    expect(src).toContain('autorun: "1"')
    expect(src).toContain('prompt: trimmedQuery')
  })

  it('includes bilingual keyword aliases for power-user slash navigation', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain("keywords: t.raw(`slash.commands.${id}.keywords`) as string[]")
    expect(src).toContain("keywords: t.raw(`modules.${id}.keywords`) as string[]")
  })

  it('documents the viewer shortcut map alongside the command center chords', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain("heading={t('groups.viewerShortcuts')}")
    expect(src).toContain('key: "Ctrl/Cmd+F"')
    expect(src).toContain('key: "j / k"')
    expect(src).toContain('key: "Esc"')
    expect(src).toContain("label: t(`viewerShortcuts.${id}.label`)")
  })

  it('hides disabled shortcut reference groups while the user is actively searching', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain('const shouldShowShortcutReference = trimmedQuery.length === 0')
    expect(src).toContain('{shouldShowShortcutReference ? (')
    expect(src).toContain("heading={t('groups.viewerShortcuts')}")
    expect(src).toContain("heading={t('groups.shortcutMap')}")
  })
})
