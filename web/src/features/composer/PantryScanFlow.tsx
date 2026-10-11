import { useEffect, useId, useRef, useState } from 'react'
import { useOnline } from '../../data/online'
import { Sheet } from '../../ui/Sheet'
import { toast } from '../../ui/Toast'
import { ManualFooter, ManualForm } from '../plan/pantry/AddSheet'
import { BarcodeSheet } from '../plan/pantry/BarcodeSheet'
import { Scanner } from '../plan/pantry/scan/Scanner'
import '../plan/pantry/pantry.css'

const BARCODE = /^\d{6,14}$/

type Step = { k: 'camera' } | { k: 'type' } | { k: 'lookup'; code: string } | { k: 'manual'; barcode: string }

/**
 * Add › Scan › Pantry barcode (Phase C spec §5): the pantry's own camera, then its own barcode sheet. This module is
 * the only importer of both and is itself lazy, so neither the camera nor the decoder enters the composer's chunk.
 * Closing at any step ends the flow; the form behind was never unmounted, so what was typed is still there.
 */
export function PantryScanFlow({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState<Step>({ k: 'camera' })
  const added = (name: string) => {
    toast(`Added ${name}`)
    onClose()
  }
  if (step.k === 'camera') {
    return <Scanner onDetect={(code) => setStep({ k: 'lookup', code })} onUnavailable={() => setStep({ k: 'type' })} onClose={onClose} />
  }
  if (step.k === 'type') return <TypeDigits onLookup={(code) => setStep({ k: 'lookup', code })} onClose={onClose} />
  if (step.k === 'manual') return <Manual barcode={step.barcode} onAdded={added} onClose={onClose} />
  return (
    <BarcodeSheet code={step.code} onClose={onClose}
      onScanAnother={() => setStep({ k: 'camera' })}
      onAddManually={(barcode) => setStep({ k: 'manual', barcode })}
      onAdded={added} />
  )
}

function TypeDigits({ onLookup, onClose }: { onLookup: (code: string) => void; onClose: () => void }) {
  const [typed, setTyped] = useState('')
  const id = useId()
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => { ref.current?.focus() }, [])
  const ok = BARCODE.test(typed)
  return (
    <Sheet open onClose={onClose} title="Type the barcode">
      <p id={`${id}-why`} className="pantry-add__nocam" role="status">
        <b>Type the barcode instead</b> The camera isn’t available here.
      </p>
      <form className="pantry-add__typed" onSubmit={(e) => { e.preventDefault(); if (ok) onLookup(typed) }}>
        <label htmlFor={id} className="ui-sr">Type barcode</label>
        <input ref={ref} id={id} className="ui-input" inputMode="numeric" autoComplete="off" enterKeyHint="search"
          placeholder="Type barcode" value={typed} aria-describedby={`${id}-why`}
          onChange={(e) => setTyped(e.target.value.replace(/\s/g, ''))} />
        <button type="submit" className="btn" disabled={!ok}>Look up</button>
      </form>
    </Sheet>
  )
}

function Manual({ barcode, onAdded, onClose }: { barcode: string; onAdded: (name: string) => void; onClose: () => void }) {
  const online = useOnline()
  return (
    <Sheet open onClose={onClose} title="Add to pantry" footer={<ManualFooter formId="composer-pantry-manual" online={online} />}>
      <ManualForm id="composer-pantry-manual" barcode={barcode} online={online} onBack={onClose} onAdded={onAdded} />
    </Sheet>
  )
}
