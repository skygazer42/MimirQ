import React, { act, useImperativeHandle } from 'react'
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
  const resultRef = React.createRef<T>()
  const Wrapper = options.wrapper ?? (({ children }: WrapperProps) => React.createElement(React.Fragment, null, children))

  const Harness = React.forwardRef<T, object>(function HookHarness(_props, ref) {
    const value = useHook()
    useImperativeHandle(ref, () => value, [value])
    return null
  })

  function render() {
    root.render(React.createElement(Wrapper, null, React.createElement(Harness, { ref: resultRef })))
  }

  act(() => {
    render()
  })

  return {
    result: resultRef as { current: T },
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
