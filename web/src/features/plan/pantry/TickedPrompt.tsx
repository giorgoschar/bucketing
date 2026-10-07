import { useState } from 'react'
import { useOnline } from '../../../data/online'
import { Sheet } from '../../../ui/Sheet'
import { PANTRY_OFFLINE, useApplyTicked } from './shoppingHooks'
import { resetTickedPrompt, useTickedOffer } from './tickedOffer'
import './prompt.css'

/** Mounted once by AppShell: the post-save "Add ticked items to the pantry?" sheet (pantry spec §4.6). */
export function TickedPrompt() {
  const count = useTickedOffer()
  // No hooks beyond the store until there is an offer: AppShell renders this on every screen.
  return count === null ? null : <PromptSheet count={count} />
}

function PromptSheet({ count }: { count: number }) {
  const online = useOnline()
  const apply = useApplyTicked()
  const [busy, setBusy] = useState(false)
  const add = async () => {
    setBusy(true)
    try {
      const out = await apply()
      if (out.ok) resetTickedPrompt()
    } finally {
      setBusy(false)
    }
  }
  return (
    <Sheet open onClose={resetTickedPrompt} title={count === 1 ? '1 ticked pantry item' : `${count} ticked pantry items`}
      footer={
        <div className="shop-prompt__acts">
          <button type="button" className="btn btn--lg" onClick={resetTickedPrompt}>Not now</button>
          <button type="button" className="btn btn--lg btn--primary" disabled={!online || busy} onClick={() => void add()}>
            Add to pantry
          </button>
        </div>
      }>
      <p className="shop-prompt__text">Add them to the pantry?</p>
      <p className="shop-prompt__note">{online ? 'Their stock goes up. Your expense stays as you saved it.' : PANTRY_OFFLINE}</p>
    </Sheet>
  )
}
