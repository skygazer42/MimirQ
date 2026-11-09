import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { icons, pageIcons } from './platform-icon-source.mjs'
import { iconCatalog } from './platform-icon-catalog.mjs'
import { iconPalette, iconColorRules, iconFillNodes, iconColorCss } from './platform-icon-colors.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const slug = (name) => name.replace(/([a-z\d])([A-Z])/g, '$1-$2').toLowerCase()
const escape = (value) => String(value).replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;')
const svgAttr = (key) => key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)
const shape = ([tag, attrs], jsx = false) => `<${tag} ${Object.entries(attrs).map(([key, value]) => `${jsx ? key : svgAttr(key)}="${escape(value)}"`).join(' ')} />`
const svg = (name, nodes, { color = false, embedded = false } = {}) => {
  const tone = color && iconColorRules[name]
  const ink = tone ? iconPalette[tone] : null
  const selector = `svg[data-platform-icon="${slug(name)}"][data-icon-appearance="color"]`
  const style = ink && !embedded ? `<style>${selector}{color:hsl(${ink[0]})}@media(prefers-color-scheme:dark){${selector}{color:hsl(${ink[1]})}}</style>` : ''
  const fill = tone ? `<g data-icon-fill="true" opacity="0.12" stroke="none">${iconFillNodes(nodes).map((node) => shape(node)).join('')}</g>` : ''
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" data-platform-icon="${slug(name)}"${tone ? ` data-icon-appearance="color" data-icon-tone="${tone}"` : ''}>${style}${fill}${nodes.map((node) => shape(node)).join('')}</svg>\n`
}
const output = (file, contents) => {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  if (!fs.existsSync(file) || fs.readFileSync(file, 'utf8') !== contents) fs.writeFileSync(file, contents)
}
const names = new Set()
for (const [name, , , , aliases] of icons) {
  for (const item of [name, ...aliases]) {
    if (names.has(item)) throw new Error(`Duplicate icon: ${item}`)
    names.add(item)
  }
}

const glyphs = [
  '// Generated from scripts/platform-icon-source.mjs. Edit the masters, then regenerate.',
  "import { createPlatformIcon } from './create-platform-icon'",
  "export type { PlatformIcon, PlatformIconProps } from './create-platform-icon'",
  '',
]
for (const [name, , , nodes, aliases] of icons) {
  const tone = iconColorRules[name]
  const colored = tone ? `, { tone: '${tone}', fill: <>${iconFillNodes(nodes).map((node) => shape(node, true)).join('')}</> }` : ''
  glyphs.push(`export const ${name} = /* @__PURE__ */ createPlatformIcon('${slug(name)}', <>${nodes.map((node) => shape(node, true)).join('')}</>${colored})`)
  if (aliases.length) glyphs.push(`export { ${aliases.map((alias) => `${name} as ${alias}`).join(', ')} }`)
  output(path.join(root, 'public/icons/ragvia', `${slug(name)}.svg`), svg(name, nodes))
  if (tone) output(path.join(root, 'public/icons/ragvia/color', `${slug(name)}.svg`), svg(name, nodes, { color: true }))
}
output(path.join(root, 'components/icons/index.tsx'), `${glyphs.join('\n')}\n`)

output(path.join(root, 'components/icons/page-icons.ts'), [
  '// Generated from scripts/platform-icon-source.mjs.',
  `import { ${[...new Set(Object.values(pageIcons))].join(', ')} } from './index'`,
  '',
  'export const PAGE_TITLE_ICONS = {',
  ...Object.entries(pageIcons).map(([page, name]) => `  '${page}': ${name},`),
  '} as const',
  '',
].join('\n'))

for (const [page, icon] of Object.entries(pageIcons)) {
  const master = icons.find(([name]) => name === icon)
  if (!master) throw new Error(`Unknown page icon: ${icon}`)
  output(path.join(root, 'public/page-title-icons', `${page}.svg`), svg(icon, master[3], { color: true }))
}
output(path.join(root, 'public/icons/ragvia/colors.css'), iconColorCss())
output(path.join(root, 'public/icons/ragvia/manifest.json'), `${JSON.stringify({ grid: 24, stroke: 1.7, icons: icons.map(([name, label, category, , aliases]) => ({ name, label, category, aliases, file: `${slug(name)}.svg`, ...(iconColorRules[name] ? { tone: iconColorRules[name], colorFile: `color/${slug(name)}.svg` } : {}) })), pages: pageIcons }, null, 2)}\n`)
output(path.join(root, 'public/icons/ragvia/index.html'), iconCatalog({ icons, slug, svg, iconColorRules }))
console.log(`Generated ${icons.length} glyphs, ${names.size} exports and ${Object.keys(pageIcons).length} page SVGs.`)
