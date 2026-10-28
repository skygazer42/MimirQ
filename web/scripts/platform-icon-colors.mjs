// Semantic icon inks, shared by the product, catalog and downloadable SVGs.
export const iconPalette = {
  source: ['176 31% 34%', '176 36% 66%'],
  knowledge: ['13.5 52% 42%', '17 70% 72%'],
  process: ['211 35% 43%', '209 42% 72%'],
  analysis: ['255 27% 46%', '255 45% 76%'],
  governance: ['148 30% 34%', '148 32% 66%'],
  pdf: ['2 55% 44%', '3 65% 70%'],
  word: ['212 52% 43%', '212 64% 73%'],
  sheet: ['151 35% 34%', '151 38% 64%'],
  slides: ['17 58% 43%', '19 70% 70%'],
  code: ['34 65% 33%', '38 58% 65%'],
  media: ['269 28% 46%', '269 40% 75%'],
  neutral: ['217 12% 42%', '215 14% 68%'],
}

// Only object glyphs have a colored appearance. Controls stay monochrome.
export const iconColorRules = {
  Dataset: 'source', KnowledgeBase: 'knowledge', Parsing: 'process',
  Chunking: 'process', KnowledgeGraph: 'analysis', Retrieval: 'knowledge',
  DataGovernance: 'governance', RuleSet: 'governance', Ingestion: 'process',
  IngestionMonitor: 'process', Quarantine: 'slides', Prompts: 'knowledge',
  Conversation: 'knowledge', ConversationAdd: 'knowledge', ConversationHistory: 'knowledge',
  Feedback: 'governance', Evaluation: 'analysis', GraphEvaluation: 'analysis',
  GraphSnapshot: 'analysis', RetrievalAblation: 'analysis', RagVisualization: 'analysis',
  Reports: 'analysis', Usage: 'analysis', Diagnostics: 'process', AuditLog: 'neutral',
  AccessReview: 'governance', Members: 'process', Groups: 'process',
  ProfileDiscovery: 'governance', Settings: 'neutral', Automation: 'process',
  Processor: 'process', LocalModel: 'process', Reranker: 'analysis', Model: 'process',
  Document: 'neutral', File: 'neutral', FilePdf: 'pdf', FileMarkdown: 'neutral',
  FileSpreadsheet: 'sheet', FileCode: 'code', FileJson: 'code', FileType: 'word',
  FileImage: 'media', FileArchive: 'code', Presentation: 'slides', Image: 'media',
}

export function iconFillNodes(nodes) {
  // Use closed body shapes only; open arrows and text strokes never become fills.
  return nodes.flatMap(([tag, attrs]) => {
    if (['rect', 'circle', 'ellipse', 'polygon'].includes(tag) && attrs.stroke !== 'none') {
      return [[tag, { ...attrs, fill: 'currentColor', stroke: 'none' }]]
    }
    if (tag === 'path' && /z/i.test(attrs.d || '')) {
      const closedBody = String(attrs.d).slice(0, String(attrs.d).search(/z/i) + 1)
      return [['path', { d: closedBody, fill: 'currentColor', stroke: 'none' }]]
    }
    return []
  })
}

export function iconColorCss() {
  const entries = Object.entries(iconPalette)
  return [
    '/* Generated from scripts/platform-icon-colors.mjs. */',
    ':root {', ...entries.map(([name, [light]]) => `  --icon-${name}: ${light};`), '}',
    '.dark, [data-theme="dark"] {', ...entries.map(([name, [, dark]]) => `  --icon-${name}: ${dark};`), '}',
    ...entries.map(([name]) => `svg[data-icon-appearance="color"][data-icon-tone="${name}"], .icon-ink-${name} { color: hsl(var(--icon-${name})); }`),
    ...entries.map(([name]) => `.icon-surface-${name} { background-color: hsl(var(--icon-${name}) / 0.08); border-color: hsl(var(--icon-${name}) / 0.18); }`),
    ...entries.map(([name]) => `.icon-border-${name} { border-color: hsl(var(--icon-${name}) / 0.18); }`),
    '',
  ].join('\n')
}
