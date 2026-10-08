import { useState } from 'react'
import { Sheet } from '../../ui/Sheet'

type Props = { open: boolean; value: string; onSave: (v: string) => void; onClose: () => void }

/** The Sheet renders its children only while open, so the draft starts from `value` on every open. */
function NotesForm({ value, onSave, onClose }: Omit<Props, 'open'>) {
  const [text, setText] = useState(value)
  return (
    <form
      className="notes-form"
      onSubmit={(e) => {
        e.preventDefault()
        onSave(text.trim())
        onClose()
      }}
    >
      <textarea className="ui-input notes-form__text" aria-label="Notes" rows={4} maxLength={500} value={text}
        enterKeyHint="done" onChange={(e) => setText(e.target.value)} />
      <button type="submit" className="btn btn--primary btn--block">Save</button>
    </form>
  )
}

export function NotesSheet({ open, value, onSave, onClose }: Props) {
  return (
    <Sheet open={open} onClose={onClose} title="Notes">
      <NotesForm value={value} onSave={onSave} onClose={onClose} />
    </Sheet>
  )
}
