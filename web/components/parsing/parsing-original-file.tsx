'use client'

import { useEffect, useState } from 'react'
import { Download, FileText } from '@/components/icons'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { Button } from '@/components/ui/button'
import styles from './parsing-compare.module.css'

/** Original files stay local; the preview does not start a parsing service. */
export function ParsingOriginalFile({ file }: Readonly<{ file: File }>) {
  const [source, setSource] = useState<{ file: File; url: string; text: string | null } | null>(null)
  useEffect(() => {
    let active = true
    const url = URL.createObjectURL(file)
    setSource({ file, url, text: null })
    if (/\.(txt|md|markdown|csv|tsv|json|xml|rst|adoc)$/i.test(file.name)) {
      void file.slice(0, 200_000).text().then((text) => {
        if (active) setSource({ file, url, text })
      }).catch(() => { /* The original remains downloadable if reading fails. */ })
    }
    return () => { active = false; URL.revokeObjectURL(url) }
  }, [file])
  const current = source?.file === file ? source : null
  const isImage = /\.(png|jpe?g|gif|webp|bmp|avif)$/i.test(file.name)
  return <>
    <div className={styles.resultToolbar}><FileText className="size-3.5 text-muted-foreground" /><span className="text-[13px]">原始文件</span>
      {current ? <Button size="icon" variant="ghost" className="ml-auto size-8" asChild><a href={current.url} download={file.name} aria-label="下载原始文件" title="下载原始文件"><Download className="size-4" /></a></Button> : null}
    </div>
    {current?.text != null ? <div className={styles.resourceBody}><pre className={styles.raw}>{current.text}</pre>{file.size > 200_000 ? <p className="p-4 text-xs text-muted-foreground">当前预览前 200 KB，下载可查看完整文件。</p> : null}</div> : isImage && current ? <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-6">
      {/* A local blob has no stable Next image optimization URL. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={current.url} alt={file.name} className="max-h-full max-w-full object-contain" />
    </div> : <div className={styles.empty}><FileTypeIcon filename={file.name} className="size-10" /><h2>{file.name}</h2><p>该格式暂不支持原文预览，可下载文件对照。</p>{current ? <Button variant="outline" size="sm" asChild><a href={current.url} download={file.name}>下载原始文件</a></Button> : null}</div>}
  </>
}
