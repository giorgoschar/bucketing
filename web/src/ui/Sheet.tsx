import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { focusables, trapTab } from './focusTrap'
import { XIcon } from './icons'

export interface SheetProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  /** Pinned below the scrolling body (primary actions). */
  footer?: ReactNode
  /** false for sheets that show something the user must acknowledge (2d's backup codes): neither a
   *  backdrop tap nor Esc closes them, only their own buttons. */
  closeOnBackdrop?: boolean
  /** Where focus lands on open; defaults to the first focusable element (the Close button). */
  initialFocus?: RefObject<HTMLElement | null>
}

/** Open sheets, innermost last: only the top one handles Esc and Tab. */
const stack: HTMLElement[] = []

export function Sheet({ open, onClose, title, children, footer, closeOnBackdrop = true, initialFocus }: SheetProps) {
  const panel = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const onCloseRef = useRef(onClose)
  const dismissableRef = useRef(closeOnBackdrop)
  useEffect(() => { onCloseRef.current = onClose; dismissableRef.current = closeOnBackdrop })

  useEffect(() => {
    if (!open || !panel.current) return
    const node = panel.current
    const opener = document.activeElement as HTMLElement | null
    stack.push(node)
    ;(initialFocus?.current ?? focusables(node)[0] ?? node).focus()
    const onKey = (e: KeyboardEvent) => {
      if (stack[stack.length - 1] !== node) return
      if (e.key === 'Escape') {
        e.preventDefault()
        if (dismissableRef.current) onCloseRef.current()
        return
      }
      trapTab(node, e)
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden' // the page behind must not scroll under the sheet
    return () => {
      document.removeEventListener('keydown', onKey)
      stack.splice(stack.indexOf(node), 1)
      document.body.style.overflow = overflow
      opener?.focus?.()
    }
  }, [open, initialFocus])

  if (!open) return null
  return createPortal(
    <div className="ui-sheet-layer">
      <div className="ui-sheet-scrim" aria-hidden="true" data-testid="sheet-backdrop"
        onClick={closeOnBackdrop ? onClose : undefined} />
      <div ref={panel} className="ui-sheet" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="ui-sheet__grab" aria-hidden="true" />
        <div className="ui-sheet__head">
          <h2 id={titleId} className="ui-sheet__title">{title}</h2>
          <button type="button" className="ui-iconbtn" aria-label="Close" onClick={onClose}><XIcon /></button>
        </div>
        <div className="ui-sheet__body">{children}</div>
        {footer && <div className="ui-sheet__foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}
