import assert from 'node:assert/strict'
import test from 'node:test'

import { checkBaseline, inspectBoundaries } from './check-feature-boundaries.mjs'

const inspect = (entries, roles = {}) => inspectBoundaries(new Map(Object.entries(entries)), roles)

test('pure models reject direct requests, dynamic imports and React', () => {
  for (const source of ["import { useState } from 'react'", "import { api } from '@/lib/api'", "const api = import('@/lib/api')", "fetch('/api')"]) {
    assert.ok(inspect({ 'app/a-model.ts': source }).length, source)
  }
})

test('pure models follow local barrels and reject hidden request owners', () => {
  const findings = inspect({
    'app/a-model.ts': "import { load } from './barrel'",
    'app/barrel.ts': "export { load } from './query'",
    'app/query.ts': "import { useQuery } from '@tanstack/react-query'",
  })
  assert.equal(findings.length, 1)
  assert.equal(findings[0].owner, 'app/a-model.ts')
  assert.equal(findings[0].file, 'app/query.ts')
})

test('type imports and strings resembling imports do not execute dependencies', () => {
  assert.deepEqual(inspect({ 'app/a-model.ts': "import type { Result } from '@/lib/api'; import { type Node } from 'react'; const text = \"import('react')\"" }), [])
})

test('pure utilities, including dependency cycles, are allowed', () => {
  assert.deepEqual(inspect({
    'app/a-model.ts': "import { n } from './values'; export const value=n+1",
    'app/values.ts': "import { value } from './a-model'; export const n=value",
  }), [])
})

test('registered views reject persistence and queries but allow local interaction state', () => {
  const roles = { views: ['app/view.tsx'] }
  assert.equal(inspect({ 'app/view.tsx': "localStorage.setItem('x','y')" }, roles).length, 1)
  assert.equal(inspect({ 'app/view.tsx': "import { useQuery } from '@tanstack/react-query'" }, roles).length, 1)
  assert.deepEqual(inspect({ 'app/view.tsx': "import { useState } from 'react'; export function View(){const [open]=useState(false);return <div>{String(open)}</div>}" }, roles), [])
})

test('baseline tracks exact counts and reports stale entries', () => {
  const findings = inspect({ 'app/a-model.ts': "import { useQuery } from '@tanstack/react-query'" })
  const baseline = [{ ...findings[0], count: 1, task: 'F9' }]
  assert.deepEqual(checkBaseline(findings, baseline), [])
  assert.match(checkBaseline([...findings, ...findings], baseline)[0], /new/)
  assert.match(checkBaseline([], baseline)[0], /stale/)
})
