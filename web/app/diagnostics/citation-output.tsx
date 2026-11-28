'use client'

import { record, text } from './diagnostics-model'
import styles from './diagnostics.module.css'

export function CitationOutput({
  data,
  documents,
}: {
  data: unknown
  documents: ReadonlyArray<{ id: string; filename: string }>
}) {
  const citations = Array.isArray(data) ? data : null
  return (
    <div className={styles.dialogBody}>
      {citations === null ? (
        <p className={styles.sectionEmpty}>引用结果未返回。</p>
      ) : citations.length > 0 ? (
        <ol className={styles.citationList}>
          {citations.map((value, index) => {
            const citation = record(value)
            const documentId = text(citation.document_id)
            const name =
              text(citation.document_name) ??
              documents.find((document) => document.id === documentId)?.filename ??
              '文档名称未取得'
            const content = text(citation.chunk_content) ?? text(citation.content)
            return (
              <li key={index}>
                <h3>{name}</h3>
                {documentId === null ? null : <p className={styles.citationIdentity}>文档 ID · {documentId}</p>}
                {content !== null ? (
                  <p className={styles.citationContent}>{content}</p>
                ) : (
                  <p className={styles.sectionEmpty}>本条引用未返回片段内容。</p>
                )}
              </li>
            )
          })}
        </ol>
      ) : (
        <p className={styles.sectionEmpty}>本次未召回引用。</p>
      )}
      <details className={styles.serviceRaw}>
        <summary>原始引用字段</summary>
        <pre className={styles.rawContent}>{JSON.stringify(data ?? null, null, 2)}</pre>
      </details>
    </div>
  )
}
