import React, { act } from 'react'
import { createRoot } from 'react-dom/client'

type WrapperProps = {
  children: React.ReactNode
}

type RenderHookOptions = {
  wrapper?: React.ComponentType<WrapperProps>
}

export function renderHook<T>(useHook: () => T, options: RenderHookOptions = {}) {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  const result: { current: T | undefined } = { current: undefined }
  const Wrapper = options.wrapper ?? (({ children }: WrapperProps) => React.createElement(React.Fragment, null, children))

  function Harness() {
    result.current = useHook()
    return null
  }

  function render() {
    root.render(React.createElement(Wrapper, null, React.createElement(Harness)))
  }

  act(() => {
    render()
  })

  return {
    result: result as { current: T },
    rerender() {
      act(() => {
        render()
      })
    },
    unmount() {
      act(() => {
        root.unmount()
      })
      container.remove()
    },
  }
}

export async function waitForAssertion(assertion: () => void, timeoutMs = 1000) {
  const deadline = Date.now() + timeoutMs
  let lastError: unknown

  while (Date.now() < deadline) {
    try {
      assertion()
      return
    } catch (error) {
      lastError = error
    }

    await act(async () => {
      await new Promise((resolve) => globalThis.setTimeout(resolve, 0))
    })
  }

  throw lastError instanceof Error ? lastError : new Error('Timed out waiting for assertion')
}
