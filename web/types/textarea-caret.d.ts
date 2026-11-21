declare module 'textarea-caret' {
  interface Coordinates {
    top: number
    left: number
    height: number
  }
  function getCaretCoordinates(
    element: HTMLInputElement | HTMLTextAreaElement,
    position: number,
    options?: { debug?: boolean },
  ): Coordinates
  export = getCaretCoordinates
}
