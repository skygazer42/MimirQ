// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from 'vitest'

import { AUTH_SCOPE_CHANGED_EVENT } from '@/lib/auth-storage'
import { useDocumentView } from './document-view'

describe('document view auth scope', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('drops persisted document context when the auth scope changes', () => {
    useDocumentView.getState().openDocument('private-doc', 'private-chunk', undefined, {
      sourceContext: {
        kind: 'chat-citation',
        messageId: 'message-1',
        documentId: 'private-doc',
        chunkContent: 'private content',
      },
    })

    window.dispatchEvent(new Event(AUTH_SCOPE_CHANGED_EVENT))

    expect(useDocumentView.getState()).toMatchObject({
      isOpen: false,
      documentId: null,
      sourceContext: null,
      documentLayouts: {},
      lastOpenedTarget: null,
    })
    expect(localStorage.getItem('mimirq_document_view_v1')).toBeNull()
  })

  it('rejects persisted context from another tenant or user', async () => {
    localStorage.setItem('mimirq_tenant_id', 'tenant-b')
    localStorage.setItem('mimirq_user_id', 'user-b')
    localStorage.setItem('mimirq_document_view_v1', JSON.stringify({
      state: {
        authScope: 'tenant-a:user-a',
        isOpen: true,
        documentId: 'private-doc',
        sourceContext: { chunkContent: 'private content' },
      },
      version: 0,
    }))

    await useDocumentView.persist.rehydrate()

    expect(useDocumentView.getState()).toMatchObject({
      isOpen: false,
      documentId: null,
      sourceContext: null,
    })
  })

  it('clears open source context when another tab changes user', () => {
    localStorage.setItem('mimirq_user_id', 'user-a')
    useDocumentView.getState().openDocument('private-doc', 'private-chunk', undefined, {
      sourceContext: {
        kind: 'chat-citation',
        messageId: 'message-1',
        documentId: 'private-doc',
        chunkContent: 'private content',
      },
    })

    localStorage.setItem('mimirq_user_id', 'user-b')
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: 'mimirq_user_id',
        oldValue: 'user-a',
        newValue: 'user-b',
      })
    )

    expect(useDocumentView.getState()).toMatchObject({
      authScope: 'default:user-b',
      isOpen: false,
      documentId: null,
      sourceContext: null,
    })
    expect(localStorage.getItem('mimirq_document_view_v1')).toBeNull()
  })
})
