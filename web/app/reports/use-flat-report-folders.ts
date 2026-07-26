'use client'

import { wrap, type Remote } from 'comlink'
import { useEffect, useRef, useState } from 'react'

import { reportClientWarning } from '@/lib/client-logging'
import { flattenFolderTree } from '@/lib/report-transforms'
import { detachPromise } from '@/lib/utils'

import type { FlatFolderRow } from '@/lib/report-transforms'
import type { DatasetReport } from '@/types'
import type { ReportTransformsWorkerApi } from '@/workers/report-transforms.worker'

export function useFlatReportFolders(folderTree: DatasetReport['folder_tree']) {
  const [flatFolders, setFlatFolders] = useState<FlatFolderRow[] | null>(null)
  const transformsWorkerRef = useRef<Worker | null>(null)
  const transformsApiRef = useRef<Remote<ReportTransformsWorkerApi> | null>(
    null
  )
  const transformsDisabledRef = useRef(false)
  const flatFoldersSeqRef = useRef(0)

  useEffect(() => {
    return () => {
      if (transformsWorkerRef.current) {
        transformsWorkerRef.current.terminate()
        transformsWorkerRef.current = null
        transformsApiRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    const seq = ++flatFoldersSeqRef.current

    if (!folderTree) {
      setFlatFolders(null)
      return
    }

    // Null => computed pending for this folder tree.
    setFlatFolders(null)

    const computeSync = () => {
      try {
        const rows = flattenFolderTree(folderTree)
        if (flatFoldersSeqRef.current === seq) setFlatFolders(rows)
      } catch (e) {
        reportClientWarning(
          'Failed to flatten folder tree; falling back to empty list',
          e
        )
        if (flatFoldersSeqRef.current === seq) setFlatFolders([])
      }
    }

    if (transformsDisabledRef.current || typeof Worker === 'undefined') {
      computeSync()
      return
    }

    let cancelled = false
    detachPromise(
      (async () => {
        try {
          if (!transformsWorkerRef.current || !transformsApiRef.current) {
            transformsWorkerRef.current = new Worker(
              new URL(
                '../../workers/report-transforms.worker.ts',
                import.meta.url
              ),
              { type: 'module' }
            )
            transformsApiRef.current = wrap<ReportTransformsWorkerApi>(
              transformsWorkerRef.current
            )
          }

          const rows =
            await transformsApiRef.current.flattenFolderTree(folderTree)
          if (cancelled) return
          if (flatFoldersSeqRef.current !== seq) return
          setFlatFolders(rows)
        } catch (e) {
          // If the environment can't load a worker bundle (or Comlink fails), keep the page functional.
          reportClientWarning(
            'Report transforms worker failed; falling back to main thread',
            e
          )
          transformsDisabledRef.current = true
          computeSync()
        }
      })()
    )

    return () => {
      cancelled = true
    }
  }, [folderTree])

  return flatFolders
}
