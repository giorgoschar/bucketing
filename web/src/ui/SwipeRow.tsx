import { type PointerEvent, type ReactNode, useRef, useState } from 'react'
import './ui-2c.css'

export const SWIPE_THRESHOLD = 0.4
export const LONG_PRESS_MS = 500
const SLOP = 8 // px of movement before a press becomes a drag

type Props = {
  children: ReactNode
  onDelete?: () => void
  onCopy?: () => void
  onLongPress?: () => void
  disabled?: boolean
}

/** A ListRow wrapper: swipe left to delete, right to copy, long-press to
 * select. The revealed buttons are real, focusable buttons, so swipe is
 * never the only path (spec §7). */
export function SwipeRow({ children, onDelete, onCopy, onLongPress, disabled }: Props) {
  const content = useRef<HTMLDivElement>(null)
  const start = useRef<{ x: number; y: number } | null>(null)
  const dxRef = useRef(0)
  const press = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const [dx, setDx] = useState(0)

  const cancelPress = () => {
    clearTimeout(press.current)
    press.current = undefined
  }
  const reset = () => {
    cancelPress()
    start.current = null
    dxRef.current = 0
    setDx(0)
  }

  const down = (e: PointerEvent<HTMLDivElement>) => {
    if (disabled) return
    start.current = { x: e.clientX, y: e.clientY }
    if (onLongPress) {
      press.current = setTimeout(() => {
        reset()
        onLongPress()
      }, LONG_PRESS_MS)
    }
  }
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const s = start.current
    if (!s) return
    const mx = e.clientX - s.x
    const my = e.clientY - s.y
    if (Math.abs(mx) > SLOP || Math.abs(my) > SLOP) cancelPress()
    if (Math.abs(mx) > SLOP && Math.abs(mx) > Math.abs(my)) {
      content.current?.setPointerCapture?.(e.pointerId)
      dxRef.current = mx
      setDx(mx)
    }
  }
  const up = () => {
    const moved = dxRef.current
    const width = content.current?.offsetWidth || 1
    const wasDragging = start.current !== null
    reset()
    if (!wasDragging) return
    if (moved / width <= -SWIPE_THRESHOLD) onDelete?.()
    else if (moved / width >= SWIPE_THRESHOLD) onCopy?.()
  }

  return (
    <div className="swipe" data-dragging={dx !== 0 || undefined}>
      {!disabled && (onDelete || onCopy) && (
        <div className="swipe__actions">
          {onCopy && <button type="button" className="swipe__copy" onClick={onCopy}>Copy</button>}
          {onDelete && <button type="button" className="swipe__delete" onClick={onDelete}>Delete</button>}
        </div>
      )}
      <div
        ref={content}
        className="swipe__content"
        data-dragging={dx !== 0 || undefined}
        style={dx ? { transform: `translateX(${dx}px)` } : undefined}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={reset}
        onContextMenu={(e) => onLongPress && e.preventDefault()}
      >
        {children}
      </div>
    </div>
  )
}
