import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const scriptsDir = path.dirname(fileURLToPath(import.meta.url))
const webRoot = path.resolve(scriptsDir, '..')
const sourceRoots = ['app', 'components'].map((directory) => path.join(webRoot, directory))
const ignoredDirectories = new Set(['.next', '.next_build', 'coverage', 'node_modules', 'test-results'])
const actionAttributes = new Set([
  'onClick',
  'onKeyDown',
  'onMouseDown',
  'onPointerDown',
  'onPress',
  'onSelect',
  'onSubmit',
])
const actionWrappers = new Set([
  'AlertDialogTrigger',
  'ConfirmDialog',
  'ContextMenuTrigger',
  'DialogTrigger',
  'DocumentDetailDialog',
  'DrawerTrigger',
  'DropdownMenuTrigger',
  'PopoverTrigger',
  'SheetTrigger',
  'ThemeCustomizer',
  'TooltipTrigger',
  'WorkbenchPanelDialog',
])

function walk(directory) {
  const files = []
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && ignoredDirectories.has(entry.name)) continue
    const absolutePath = path.join(directory, entry.name)
    if (entry.isDirectory()) files.push(...walk(absolutePath))
    else if (
      entry.isFile() &&
      absolutePath.endsWith('.tsx') &&
      !/\.(?:test|spec|stories)\.tsx$/.test(absolutePath)
    ) {
      files.push(absolutePath)
    }
  }
  return files
}

function tagNameNode(node) {
  return ts.isJsxElement(node) ? node.openingElement.tagName : node.tagName
}

function tagName(node) {
  const name = tagNameNode(node)
  return ts.isIdentifier(name) ? name.text : name.getText()
}

function attributes(node) {
  return ts.isJsxElement(node) ? node.openingElement.attributes : node.attributes
}

function hasPermanentDisabledAttribute(node) {
  const disabled = attributes(node).properties.find(
    (property) => ts.isJsxAttribute(property) && property.name.text === 'disabled'
  )
  if (!disabled || !ts.isJsxAttribute(disabled)) return false
  if (!disabled.initializer) return true
  return (
    ts.isJsxExpression(disabled.initializer) &&
    disabled.initializer.expression?.kind === ts.SyntaxKind.TrueKeyword
  )
}

function hasDirectAction(node) {
  return attributes(node).properties.some((property) => {
    if (ts.isJsxSpreadAttribute(property)) return true
    if (!ts.isJsxAttribute(property)) return false
    return property.name.text === 'asChild' || actionAttributes.has(property.name.text)
  })
}

function isSubmitControl(node) {
  return attributes(node).properties.some((property) => {
    if (!ts.isJsxAttribute(property) || property.name.text !== 'type') return false
    return property.initializer?.getText().replaceAll(/[{}"']/g, '') === 'submit'
  })
}

function hasActionWrapper(node, source) {
  let jsxAncestorDepth = 0
  for (let parent = node.parent; parent; parent = parent.parent) {
    if (ts.isJsxAttribute(parent) && parent.name.text === 'trigger') return true
    if (ts.isJsxElement(parent) || ts.isJsxSelfClosingElement(parent)) {
      const name = tagName(parent)
      if (name === 'form' || actionWrappers.has(name)) return true
      const parentText = jsxAncestorDepth === 0 ? parent.getText(source) : ''
      if (
        parentText.includes('group-focus-within') &&
        parentText.includes('group-hover')
      ) {
        return true
      }
      jsxAncestorDepth += 1
    }
  }
  return false
}

const failures = []
let controlsChecked = 0

for (const sourcePath of sourceRoots.flatMap(walk)) {
  const sourceText = fs.readFileSync(sourcePath, 'utf8')
  const source = ts.createSourceFile(
    sourcePath,
    sourceText,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX
  )

  function visit(node) {
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const name = tagName(node)
      if (name === 'button' || name === 'Button') {
        controlsChecked += 1
        const bound =
          hasDirectAction(node) ||
          hasPermanentDisabledAttribute(node) ||
          isSubmitControl(node) ||
          hasActionWrapper(node, source)
        if (!bound) {
          const line = source.getLineAndCharacterOfPosition(node.getStart()).line + 1
          failures.push(`${path.relative(webRoot, sourcePath)}:${line}`)
        }
      }
    }
    ts.forEachChild(node, visit)
  }

  visit(source)
}

if (failures.length > 0) {
  console.error('[interactive-controls] FAIL: enabled buttons without an action or trigger:')
  for (const failure of failures) console.error(`- ${failure}`)
  process.exitCode = 1
} else {
  console.log(`[interactive-controls] OK: ${controlsChecked} buttons have actions, triggers, or explicit disabled states`)
}
