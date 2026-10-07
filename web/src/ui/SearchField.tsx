import { useEffect, useRef, useState } from 'react'
import './ui-2c.css'

export const SEARCH_DEBOUNCE_MS = 250

type Props = { value: string; onChange: (value: string) => void; placeholder?: string; label?: string }

export function SearchField({ value, onChange, placeholder = 'Search', label = 'Search transactions' }: Props) {
  const [text, setText] = useState(value)
  const sent = useRef(value)

  useEffect(() => {
    if (value !== sent.current) {
      sent.current = value
      setText(value)
    }
  }, [value])

  useEffect(() => {
    if (text === sent.current) return
    const t = setTimeout(() => {
      sent.current = text
      onChange(text)
    }, SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [text, onChange])

  return (
    <div className="search" role="search">
      <input
        type="search"
        inputMode="search"
        enterKeyHint="search"
        autoComplete="off"
        aria-label={label}
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {text && (
        <button
          type="button"
          className="search__clear"
          aria-label="Clear search"
          onClick={() => {
            sent.current = ''
            setText('')
            onChange('')
          }}
        >
          ×
        </button>
      )}
    </div>
  )
}
