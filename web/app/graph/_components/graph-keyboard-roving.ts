export function getNextKeyboardRovingIndex(
  currentIndex: number,
  itemCount: number,
  direction: 1 | -1
): number {
  if (!Number.isFinite(itemCount) || itemCount <= 0) return -1

  if (!Number.isFinite(currentIndex) || currentIndex < 0 || currentIndex >= itemCount) {
    return direction === -1 ? itemCount - 1 : 0
  }

  return (currentIndex + direction + itemCount) % itemCount
}
