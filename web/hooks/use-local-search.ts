"use client"

import { useEffect, useMemo, useState } from 'react'
import MiniSearch from 'minisearch'

interface SearchItem {
  id: string
  [key: string]: unknown
}

function parseFields(serialized: string): string[] {
  return JSON.parse(serialized) as string[]
}

export function useLocalSearch<T extends SearchItem>(
  data: T[],
  options: { fields: string[]; storeFields?: string[] }
) {
  const [term, setTerm] = useState('')
  const fieldsKey = JSON.stringify(options.fields)
  const storeFieldsKey = JSON.stringify(options.storeFields || options.fields)

  // Initialize MiniSearch
  const miniSearch = useMemo(() => {
    return new MiniSearch({
      fields: parseFields(fieldsKey), // fields to index for full-text search
      storeFields: parseFields(storeFieldsKey), // fields to return with search results
      searchOptions: {
        boost: { filename: 2 },
        fuzzy: 0.2,
        prefix: true
      }
    })
  }, [fieldsKey, storeFieldsKey])

  // Index data when it changes
  useEffect(() => {
    miniSearch.removeAll()
    miniSearch.addAll(data)
  }, [data, miniSearch])

  // Perform search
  const results = useMemo(() => {
    if (!term.trim()) return data
    
    const searchResults = miniSearch.search(term)
    // Map search results back to original data items or return stored fields
    const resultIds = new Set(searchResults.map(r => r.id))
    return data.filter(item => resultIds.has(item.id))
  }, [term, data, miniSearch])

  return {
    term,
    setTerm,
    results,
    count: results.length
  }
}
