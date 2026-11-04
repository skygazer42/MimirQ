// @vitest-environment happy-dom

import { act, createRef, useState, type FormEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { NextIntlClientProvider } from 'next-intl'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import commonMessages from '@/i18n/messages/zh-CN/common'
import { IconButton } from './icon-button'
import { Progress } from './progress'
import { SearchInput } from './search-input'
import { Switch } from './switch'
import { TagInput } from './tag-input'

let container: HTMLDivElement
let root: ReturnType<typeof createRoot>

function render(children: ReactNode) {
  act(() =>
    root.render(
      <NextIntlClientProvider locale="zh-CN" timeZone="UTC" messages={commonMessages}>
        {children}
      </NextIntlClientProvider>,
    ),
  )
}

function typeText(input: HTMLInputElement, value: string) {
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.restoreAllMocks()
})

describe('Switch event and state ownership', () => {
  it('runs a supplied click once and still toggles uncontrolled state', () => {
    const click = vi.fn()
    const change = vi.fn()
    const ref = createRef<HTMLButtonElement>()
    render(<Switch ref={ref} aria-label="feature" onClick={click} onCheckedChange={change} />)
    const button = container.querySelector('button')!
    act(() => button.click())
    expect(click).toHaveBeenCalledOnce()
    expect(change).toHaveBeenCalledExactlyOnceWith(true)
    expect(button.getAttribute('aria-checked')).toBe('true')
    expect(ref.current).toBe(button)
  })

  it('leaves controlled state to its caller while reporting the proposed value', () => {
    const click = vi.fn()
    const change = vi.fn()
    render(<Switch checked={false} onClick={click} onCheckedChange={change} />)
    const button = container.querySelector('button')!
    act(() => button.click())
    expect(click).toHaveBeenCalledOnce()
    expect(change).toHaveBeenCalledExactlyOnceWith(true)
    expect(button.getAttribute('aria-checked')).toBe('false')
  })

  it('honors caller default prevention and native disabled behavior', () => {
    const change = vi.fn()
    const click = vi.fn((event: ReactMouseEvent<HTMLButtonElement>) => event.preventDefault())
    render(<Switch onClick={click} onCheckedChange={change} />)
    act(() => container.querySelector('button')!.click())
    expect(click).toHaveBeenCalledOnce()
    expect(change).not.toHaveBeenCalled()
    render(<Switch disabled onClick={click} onCheckedChange={change} />)
    act(() => container.querySelector('button')!.click())
    expect(click).toHaveBeenCalledOnce()
    expect(change).not.toHaveBeenCalled()
  })
})

describe('TagInput shared add paths', () => {
  it.each(['enter', 'blur', 'button', 'paste'] as const)('respects the existing tag limit on %s', (path) => {
    function Tags() {
      const [tags, setTags] = useState(['one', 'two'])
      return (
        <>
          <TagInput value={tags} onValueChange={setTags} maxTags={2} />
          <output>{JSON.stringify(tags)}</output>
        </>
      )
    }
    render(<Tags />)
    const input = container.querySelector('input')!
    if (path === 'paste') {
      act(() => {
        const event = new Event('paste', { bubbles: true, cancelable: true })
        Object.defineProperty(event, 'clipboardData', { value: { getData: () => 'three,four' } })
        input.dispatchEvent(event)
      })
    } else {
      typeText(input, 'three')
      act(() => {
        if (path === 'enter')
          input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }))
        else if (path === 'blur') input.dispatchEvent(new FocusEvent('focusout', { bubbles: true }))
        else Array.from(container.querySelectorAll('button')).at(-1)!.click()
      })
    }
    expect(container.querySelector('output')!.textContent).toBe('["one","two"]')
  })

  it('fills the remaining slot with normalized unique tags and retains unlimited mode', () => {
    const change = vi.fn()
    render(<TagInput value={['one']} onValueChange={change} maxTags={2} />)
    typeText(container.querySelector('input')!, 'ONE, #two, three')
    act(() =>
      container.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })),
    )
    expect(change).toHaveBeenLastCalledWith(['one', 'two'])
    render(<TagInput value={['one']} onValueChange={change} maxTags={0} />)
    typeText(container.querySelector('input')!, 'two,three')
    act(() =>
      container.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })),
    )
    expect(change).toHaveBeenLastCalledWith(['one', 'two', 'three'])
  })

  it('preserves existing over-limit values without appending another tag', () => {
    const change = vi.fn()
    render(<TagInput value={['one', 'two', 'three']} onValueChange={change} maxTags={2} />)
    typeText(container.querySelector('input')!, 'four')
    act(() =>
      container.querySelector('input')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })),
    )
    expect(change).toHaveBeenLastCalledWith(['one', 'two', 'three'])
  })
})

describe('Progress native value semantics', () => {
  it.each([
    { value: 0, max: 100, state: 'loading', transform: 'translateX(-100%)' },
    { value: 25, max: 50, state: 'loading', transform: 'translateX(-50%)' },
    { value: 50, max: 50, state: 'complete', transform: 'translateX(-0%)' },
  ])('exposes value $value of max $max with the same visual fraction', ({ value, max, state, transform }) => {
    const ref = createRef<HTMLDivElement>()
    render(<Progress ref={ref} value={value} max={max} aria-label="upload" />)
    const progress = container.querySelector('[role="progressbar"]')!
    expect(progress.getAttribute('aria-valuenow')).toBe(String(value))
    expect(progress.getAttribute('aria-valuemax')).toBe(String(max))
    expect(progress.getAttribute('data-state')).toBe(state)
    expect((progress.firstElementChild as HTMLElement).style.transform).toBe(transform)
    expect(ref.current).toBe(progress)
  })

  it.each([null, undefined])('retains indeterminate semantics for %s', (value) => {
    render(<Progress value={value} aria-label="upload" />)
    const progress = container.querySelector('[role="progressbar"]')!
    expect(progress.hasAttribute('aria-valuenow')).toBe(false)
    expect(progress.getAttribute('data-state')).toBe('indeterminate')
    expect((progress.firstElementChild as HTMLElement).style.transform).toBe('translateX(-100%)')
  })

  it('keeps Radix invalid-range diagnostics and the same indicator fraction after its fallback', () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    render(<Progress value={20} max={0} />)
    let progress = container.querySelector('[role="progressbar"]')!
    expect(progress.getAttribute('aria-valuemax')).toBe('100')
    expect(progress.getAttribute('aria-valuenow')).toBe('20')
    expect((progress.firstElementChild as HTMLElement).style.transform).toBe('translateX(-80%)')
    render(<Progress value={60} max={50} />)
    progress = container.querySelector('[role="progressbar"]')!
    expect(progress.hasAttribute('aria-valuenow')).toBe(false)
    expect(progress.getAttribute('data-state')).toBe('indeterminate')
    expect((progress.firstElementChild as HTMLElement).style.transform).toBe('translateX(-100%)')
    expect(errors).toHaveBeenCalledTimes(2)
  })
})

describe('SearchInput clear behavior', () => {
  it.each(['disabled', 'readOnly'] as const)('does not clear a %s input', (mode) => {
    const change = vi.fn()
    const clear = vi.fn()
    render(<SearchInput value="query" onValueChange={change} onClear={clear} {...{ [mode]: true }} />)
    const input = container.querySelector('input')!
    const button = container.querySelector('button')!
    act(() => button.click())
    expect(button.disabled).toBe(true)
    expect(input.value).toBe('query')
    expect(change).not.toHaveBeenCalled()
    expect(clear).not.toHaveBeenCalled()
  })

  it('clears an editable field once and restores focus through the forwarded ref', () => {
    const ref = createRef<HTMLInputElement>()
    const change = vi.fn()
    const clear = vi.fn()
    function Search() {
      const [value, setValue] = useState('query')
      return (
        <SearchInput
          ref={ref}
          value={value}
          onValueChange={(next) => {
            change(next)
            setValue(next)
          }}
          onClear={clear}
        />
      )
    }
    render(<Search />)
    act(() => container.querySelector('button')!.click())
    expect(change).toHaveBeenCalledExactlyOnceWith('')
    expect(clear).toHaveBeenCalledOnce()
    expect(ref.current?.value).toBe('')
    expect(document.activeElement).toBe(ref.current)
  })
})

describe('IconButton native and Slot contract', () => {
  it('renders its single slotted link with a label and preserves both click handlers', () => {
    const parentClick = vi.fn()
    const childClick = vi.fn((event: ReactMouseEvent<HTMLAnchorElement>) => event.preventDefault())
    render(
      <IconButton asChild label="Download" onClick={parentClick}>
        <a href="https://example.test/file.txt" onClick={childClick}>
          <svg />
        </a>
      </IconButton>,
    )
    const link = container.querySelector('a')!
    expect(link.getAttribute('href')).toBe('https://example.test/file.txt')
    expect(link.getAttribute('aria-label')).toBe('Download')
    expect(link.getAttribute('title')).toBe('Download')
    expect(container.querySelector('button')).toBeNull()
    act(() => link.click())
    expect(parentClick).toHaveBeenCalledOnce()
    expect(childClick).toHaveBeenCalledOnce()
  })

  it('keeps native icon actions from submitting their enclosing form', () => {
    const submit = vi.fn((event: FormEvent<HTMLFormElement>) => event.preventDefault())
    const click = vi.fn()
    render(
      <form onSubmit={submit}>
        <IconButton label="Action" onClick={click}>
          <svg />
        </IconButton>
      </form>,
    )
    act(() => container.querySelector('button')!.click())
    expect(click).toHaveBeenCalledOnce()
    expect(submit).not.toHaveBeenCalled()
    expect(container.querySelector('button')!.getAttribute('aria-label')).toBe('Action')
  })
})
