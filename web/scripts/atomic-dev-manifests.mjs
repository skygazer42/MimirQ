import { randomUUID } from 'node:crypto'

// Next's dev route loader can read these mutable assets during a new emission.
// Publish a complete replacement instead of truncating the currently visible file.
const DEV_ASSET = /\.(?:json|js)$/i
const SHARING_LOCK_DELAYS = [10, 30, 70, 150, 310, 630]

export function versionRootLayoutFilename(filename) {
  return (pathData, assetInfo) => {
    if (pathData.chunk.name === 'app/layout') return 'static/chunks/[name].[contenthash:8].js'
    return typeof filename === 'function' ? filename(pathData, assetInfo) : filename
  }
}

export function createAtomicManifestFileSystem(fileSystem) {
  const output = Object.create(fileSystem)
  output.writeFile = (filename, content, ...args) => {
    const callback = args.pop()
    if (!DEV_ASSET.test(filename)) {
      fileSystem.writeFile(filename, content, ...args, callback)
      return
    }
    const temporary = `${filename}.ragvia-${process.pid}-${randomUUID()}.tmp`
    fileSystem.writeFile(temporary, content, ...args, error => {
      if (error) { callback(error); return }
      // Both files live in the same directory, so replacement is atomic.
      // Windows static-file readers can briefly hold a sharing lock. Keep the
      // previous complete asset visible while retrying only that measured case.
      const publish = attempt => fileSystem.rename(temporary, filename, renameError => {
        if (renameError && process.platform === 'win32' && ['EPERM', 'EBUSY'].includes(renameError.code) && attempt < SHARING_LOCK_DELAYS.length) {
          setTimeout(() => publish(attempt + 1), SHARING_LOCK_DELAYS[attempt])
          return
        }
        callback(renameError)
      })
      publish(0)
    })
  }
  return output
}

export class AtomicDevManifestsPlugin {
  apply(compiler) {
    if (compiler.options.mode !== 'development') return
    compiler.hooks.afterEnvironment.tap('RagviaAtomicDevManifests', () => {
      compiler.outputFileSystem = createAtomicManifestFileSystem(compiler.outputFileSystem)
    })
  }
}
