declare module 'textarea-caret' {
  interface Coordinates {
    top: number;
    left: number;
    height: number;
  }
  function getCaretCoordinates(element: HTMLElement, position: number, options?: any): Coordinates;
  export = getCaretCoordinates;
}
