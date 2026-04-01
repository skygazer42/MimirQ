function installPdfJsCompatPolyfills() {
  if (typeof Promise.withResolvers !== 'function') {
    Object.defineProperty(Promise, 'withResolvers', {
      configurable: true,
      writable: true,
      value() {
        let resolve = () => {}
        let reject = () => {}
        const promise = new Promise((innerResolve, innerReject) => {
          resolve = innerResolve
          reject = innerReject
        })

        return { promise, resolve, reject }
      },
    })
  }

  if (typeof Map.prototype.getOrInsertComputed !== 'function') {
    Object.defineProperty(Map.prototype, 'getOrInsertComputed', {
      configurable: true,
      writable: true,
      value(key, compute) {
        if (this.has(key)) {
          return this.get(key)
        }

        const value = compute(key)
        this.set(key, value)
        return value
      },
    })
  }
}

installPdfJsCompatPolyfills()

await import('../pdfjs/build/pdf.worker.mjs')
