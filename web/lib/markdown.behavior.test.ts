// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest'

import { scrollToElementId } from './markdown'

describe('scrollToElementId', () => {
  it('scrolls a target inside the specified scroll container', () => {
    document.body.innerHTML = `
      <div class="parsing-md-scroll">
        <div id="target">Heading</div>
      </div>
    `

    const container = document.querySelector('.parsing-md-scroll') as HTMLDivElement | null
    const target = document.getElementById('target') as HTMLDivElement | null

    expect(container).not.toBeNull()
    expect(target).not.toBeNull()

    const scrollContainer = container!
    const heading = target!

    let scrollTop = 120
    Object.defineProperty(scrollContainer, 'scrollTop', {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => {
        scrollTop = value
      },
    })
    Object.defineProperty(scrollContainer, 'clientHeight', {
      configurable: true,
      value: 320,
    })

    const scrollTo = vi.fn(({ top }: { top: number }) => {
      scrollTop = top
    })
    scrollContainer.scrollTo = scrollTo as unknown as typeof scrollContainer.scrollTo
    scrollContainer.getBoundingClientRect = () =>
      ({
        top: 100,
        left: 0,
        bottom: 420,
        right: 600,
        width: 600,
        height: 320,
        x: 0,
        y: 100,
        toJSON: () => ({}),
      }) as DOMRect

    const scrollIntoView = vi.fn()
    heading.scrollIntoView = scrollIntoView as unknown as typeof heading.scrollIntoView
    heading.getBoundingClientRect = () =>
      ({
        top: 380,
        left: 0,
        bottom: 420,
        right: 320,
        width: 320,
        height: 40,
        x: 0,
        y: 380,
        toJSON: () => ({}),
      }) as DOMRect

    expect(
      scrollToElementId('target', {
        behavior: 'auto',
        scrollContainerSelector: '.parsing-md-scroll',
      })
    ).toBe(true)

    expect(scrollTo).toHaveBeenCalledWith({
      top: 400,
      behavior: 'auto',
    })
    expect(scrollIntoView).not.toHaveBeenCalled()
  })
})
