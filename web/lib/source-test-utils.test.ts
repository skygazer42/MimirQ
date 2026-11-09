import { describe, expect, it } from 'vitest'
import { sourceCssDeclarations, sourceJsxAttributes, sourceObjectProperties } from './source-test-utils'

describe('semantic source contracts', () => {
  it('reads JSX independently of formatting and rejects fake snippets', () => {
    const source = `const fake = '<Glyph color="wrong" />';
      // <Glyph color="also-wrong" />
      export function View() { return <Glyph className={styles.title} appearance='color' aria-hidden /> }`
    expect(sourceJsxAttributes(source, 'Glyph')).toEqual([
      { className: 'styles.title', appearance: 'color', 'aria-hidden': 'true' },
    ])
    expect(sourceJsxAttributes(source, 'Absent')).toEqual([])
  })

  it('reads real navigation objects and retains order without evaluating them', () => {
    const source = `const fake = "{ href: '/wrong', icon: Wrong }";
      const items = [{ href: '/datasets', icon: Dataset }, { icon: KnowledgeBase, href: "/knowledge" }];`
    expect(sourceObjectProperties(source, ['icon', 'href'])).toEqual([
      { href: '/datasets', icon: 'Dataset' }, { icon: 'KnowledgeBase', href: '/knowledge' },
    ])
  })

  it('distinguishes root styles from narrow container overrides', () => {
    const source = `.workspace { display: flex; min-height: 0 }
      @container app (max-width:600px) { .workspace { display:grid } }
      .workspace { overflow: hidden }
      /* .workspace { color: pink } */`
    expect(sourceCssDeclarations(source, '.workspace')).toEqual({ display: 'flex', 'min-height': '0', overflow: 'hidden' })
    expect(sourceCssDeclarations(source, '.workspace', 'app (max-width:600px)')).toEqual({ display: 'grid' })
    expect(sourceCssDeclarations(source, '.absent')).toEqual({})
  })

  it('requires every named property and matches exact selectors', () => {
    expect(sourceObjectProperties('const item = { href: "/", other: true }', ['href', 'icon'])).toEqual([])
    expect(sourceCssDeclarations('.workspace-title { display:flex }', '.workspace')).toEqual({})
    expect(sourceCssDeclarations('.panel[hidden], .scrollPanel[hidden] { display:none }', '.panel[hidden]'))
      .toEqual({ display: 'none' })
  })
})
