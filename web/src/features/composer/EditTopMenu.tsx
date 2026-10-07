import { useState } from 'react'
import { Sheet } from './bridge'

const MoreIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false" className="ui-icon">
    <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
  </svg>
)

/** Edit mode's overflow: Delete (with its own confirm in the form). */
export function EditTopMenu({ onDelete }: { onDelete: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className="ui-iconbtn composer__menu" aria-label="More actions" onClick={() => setOpen(true)}>
        <MoreIcon />
      </button>
      <Sheet open={open} onClose={() => setOpen(false)} title="Entry">
        <button type="button" className="btn btn--lg btn--block btn--danger"
          onClick={() => {
            setOpen(false)
            onDelete()
          }}>
          Delete
        </button>
      </Sheet>
    </>
  )
}
