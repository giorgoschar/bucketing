/** Focus helpers for modals (Sheet, the scan overlay). */
const FOCUSABLE =
  'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
export const focusables = (root: HTMLElement) => Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))

/** Keep Tab and Shift+Tab inside `node` (a modal). Also used by the full-screen scan overlay. */
export function trapTab(node: HTMLElement, e: KeyboardEvent): void {
  if (e.key !== 'Tab') return
  const items = focusables(node)
  if (items.length === 0) {
    e.preventDefault()
    node.focus()
    return
  }
  const first = items[0]
  const last = items[items.length - 1]
  if (e.shiftKey && (document.activeElement === first || !node.contains(document.activeElement))) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && (document.activeElement === last || !node.contains(document.activeElement))) {
    e.preventDefault()
    first.focus()
  }
}
