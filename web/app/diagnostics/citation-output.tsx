'use client'

import { record,text } from './diagnostics-model'
import styles from './diagnostics.module.css'

export function CitationOutput({data,documents}:{data:unknown;documents:ReadonlyArray<{id:string;filename:string}>}) {
  const citations=Array.isArray(data)?data:[]
  return <div className={styles.dialogBody}>
    {citations.length?<ol className={styles.citationList}>{citations.map((value,index)=>{
      const citation=record(value),id=text(citation.document_id)
      const name=text(citation.document_name)??documents.find(document=>document.id===id)?.filename??'文档名称未取得'
      const content=text(citation.chunk_content)??text(citation.content)
      return <li key={index}>
        <h3>{name}</h3>
        {id?<p className={styles.citationIdentity}>文档 ID · {id}</p>:null}
        {content?<p className={styles.citationContent}>{content}</p>:<p className={styles.sectionEmpty}>本条引用未返回片段内容。</p>}
      </li>
    })}</ol>:<p className={styles.sectionEmpty}>本次未召回引用。</p>}
    <details className={styles.serviceRaw}><summary>原始引用字段</summary><pre className={styles.rawContent}>{JSON.stringify(data??null,null,2)}</pre></details>
  </div>
}
