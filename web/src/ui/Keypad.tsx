import { useRef } from 'react'
import { BackspaceIcon } from './composer-icons'
import './composer-kit.css'

export type KeypadKey = '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9' | '.' | 'back' | 'clear'

const LAYOUT: KeypadKey[] = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '0', 'back']
const NAMES: Partial<Record<KeypadKey, string>> = { '.': 'Decimal point', back: 'Delete last digit' }
const LONG_PRESS_MS = 500

/** The composer keypad: 12 keys in 48 px rows; a long press on backspace clears the amount. */
export function Keypad({ onKey, hidden = false }: { onKey: (k: KeypadKey) => void; hidden?: boolean }) {
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const cleared = useRef(false)
  const down = () => {
    cleared.current = false
    timer.current = setTimeout(() => {
      cleared.current = true
      onKey('clear')
    }, LONG_PRESS_MS)
  }
  const up = () => clearTimeout(timer.current)
  return (
    <div className="keypad keypad--tight" role="group" aria-label="Amount keypad" hidden={hidden}>
      {LAYOUT.map((k) => (
        <button
          key={k}
          type="button"
          className="keypad__key"
          aria-label={NAMES[k] ?? k}
          onPointerDown={k === 'back' ? down : undefined}
          onPointerUp={k === 'back' ? up : undefined}
          onPointerLeave={k === 'back' ? up : undefined}
          onPointerCancel={k === 'back' ? up : undefined}
          onContextMenu={k === 'back' ? (e) => e.preventDefault() : undefined}
          onClick={() => {
            if (k === 'back' && cleared.current) {
              cleared.current = false
              return
            }
            onKey(k)
          }}
        >
          {k === 'back' ? <BackspaceIcon /> : k}
        </button>
      ))}
    </div>
  )
}
