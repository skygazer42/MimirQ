import fs from 'node:fs'
import path from 'node:path'
import { execSync } from 'node:child_process'

import ts from 'typescript'
import { describe, expect, it } from 'vitest'

function getJsxAttributeName(attribute: ts.JsxAttribute, sourceFile: ts.SourceFile): string {
  return ts.isIdentifier(attribute.name) ? attribute.name.text : attribute.name.getText(sourceFile)
}

describe('icon button accessibility audit', () => {
  it('ensures icon-sized Button usages expose an accessible name source', () => {
    const repoRoot = path.resolve(__dirname, '..', '..')
    const files = execSync("rg --files web/app web/components -g '*.tsx'", {
      cwd: repoRoot,
      encoding: 'utf8',
    })
      .trim()
      .split('\n')
      .filter(Boolean)

    const offenders: string[] = []

    for (const relativeFile of files) {
      const fullPath = path.join(repoRoot, relativeFile)
      const src = fs.readFileSync(fullPath, 'utf8')
      const sourceFile = ts.createSourceFile(fullPath, src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

      const visit = (node: ts.Node) => {
        if (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) {
          const tagName = node.tagName.getText(sourceFile)
          const attributes = node.attributes.properties.filter(ts.isJsxAttribute)
          const names = new Set(attributes.map((attribute) => getJsxAttributeName(attribute, sourceFile)))
          const line = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1

          const hasStringAttribute = (name: string, expected?: string) => {
            const attribute = attributes.find((item) => getJsxAttributeName(item, sourceFile) === name)
            if (!attribute?.initializer) return false
            if (!expected) return true
            if (ts.isStringLiteral(attribute.initializer)) return attribute.initializer.text === expected
            if (
              ts.isJsxExpression(attribute.initializer) &&
              attribute.initializer.expression &&
              ts.isStringLiteral(attribute.initializer.expression)
            ) {
              return attribute.initializer.expression.text === expected
            }
            return false
          }

          if (tagName === 'Button' && hasStringAttribute('size', 'icon')) {
            if (!names.has('aria-label') && !names.has('title')) {
              offenders.push(`${relativeFile}:${line}`)
            }
          }

          if (tagName === 'IconButton' && !names.has('label')) {
            offenders.push(`${relativeFile}:${line}`)
          }
        }

        ts.forEachChild(node, visit)
      }

      visit(sourceFile)
    }

    expect(offenders).toEqual([])
  })
})
