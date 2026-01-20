export const UPLOAD_ALLOWED_EXTENSIONS = [
  '.pdf',
  '.txt',
  '.md',
  '.rst',
  '.adoc',
  '.asciidoc',
  '.tex',
  '.yaml',
  '.yml',
  '.toml',
  '.sql',
  '.log',
  '.conf',
  '.ini',
  '.cfg',
  '.env',
  '.properties',
  '.patch',
  '.diff',
  '.srt',
  '.vtt',
  '.mk',
  '.doc',
  '.docx',
  '.ppt',
  '.pptx',
  '.xls',
  '.xlsx',
  '.csv',
  '.html',
  '.htm',
  '.json',
  '.jsonl',
  '.ndjson',
  '.xml',
  '.rss',
  '.atom',
  '.graphql',
  '.gql',
  '.proto',
  '.tf',
  '.hcl',
] as const

export type UploadAllowedExtension = (typeof UPLOAD_ALLOWED_EXTENSIONS)[number]

export const UPLOAD_ACCEPT = UPLOAD_ALLOWED_EXTENSIONS.join(',')
export const UPLOAD_ACCEPT_WITH_ZIP = `${UPLOAD_ACCEPT},.zip`

export const ZIP_ALLOWED_EXTENSIONS = new Set(UPLOAD_ALLOWED_EXTENSIONS.map((ext) => ext.replace(/^\./, '')))

