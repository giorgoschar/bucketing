import { lazy, Suspense, useId, useRef, useState } from 'react'
import { useOnline } from '../../../data/online'
import { Sheet } from '../../../ui/Sheet'
import { OFFLINE_WRITE } from './BarcodeSheet'
import { editBody, type EditField, type EditForm, initialForm, OTHER, UNITS } from './edit'
import { useStockWrites } from './hooks'
import { ScanIcon } from './icons'
import type { StockDetail } from './types'

/** The camera and its decoder: the same lazy chunk Add to pantry uses. */
const Scanner = lazy(() => import('./scan/Scanner').then((m) => ({ default: m.Scanner })))

/** Detail › Edit (polish P1): the product's name, brand, size and barcode. Online only. */
export function EditSheet({ d, onClose }: { d: StockDetail; onClose: () => void }) {
  const online = useOnline()
  const writes = useStockWrites(d.id)
  const base = useId()
  const [f, setF] = useState<EditForm>(() => initialForm(d))
  const [error, setError] = useState<{ text: string; field: EditField | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [noCamera, setNoCamera] = useState(false)
  const nameRef = useRef<HTMLInputElement>(null)
  const barcodeRef = useRef<HTMLInputElement>(null)
  const set = (k: keyof EditForm) => (e: { target: { value: string } }) => {
    setF((x) => ({ ...x, [k]: k === 'barcode' ? e.target.value.replace(/\s/g, '') : e.target.value }))
    setError(null)
  }

  const save = async () => {
    if (!online || busy) return
    const r = editBody(d, f)
    if ('error' in r) return setError({ text: r.error, field: r.field })
    if (Object.keys(r.body).length === 0) return onClose()
    setBusy(true)
    setError(null)
    const out = await writes.edit(r.body)
    setBusy(false)
    if (out.ok) return onClose()
    if (out.kind !== 'auth') setError({ text: out.message, field: out.status === 409 ? 'barcode' : null })
  }

  const field = (k: 'name' | 'brand', label: string, extra: object = {}) => (
    <div className="ui-field">
      <label className="ui-field__label" htmlFor={`${base}-${k}`}>{label}</label>
      <input id={`${base}-${k}`} className="ui-input" value={f[k]} onChange={set(k)} autoComplete="off" {...extra} />
    </div>
  )
  const errId = `${base}-error`
  /** The field the error is about is marked invalid and described by it (review M-4). */
  const bad = (k: EditField) => (error?.field === k ? { 'aria-invalid': true, 'aria-describedby': errId } : {})
  return (
    <>
      <Sheet open onClose={onClose} title="Edit product" initialFocus={nameRef}
        footer={
          <div className="pantry-sheet__foot">
            {!online && <p className="pantry-offline">{OFFLINE_WRITE}</p>}
            <button type="submit" form={`${base}-form`} className="btn btn--primary btn--block btn--lg" disabled={!online || busy}>
              {busy ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        }>
        <form id={`${base}-form`} className="pantry-manual" noValidate onSubmit={(e) => { e.preventDefault(); void save() }}>
          {field('name', 'Name', { ref: nameRef, maxLength: 200, ...bad('name') })}
          {field('brand', 'Brand', { maxLength: 120 })}
          <div className="pantry-manual__size">
            <div className="ui-field">
              <label className="ui-field__label" htmlFor={`${base}-size`}>Size</label>
              <input id={`${base}-size`} className="ui-input" inputMode="decimal" autoComplete="off" value={f.size}
                onChange={set('size')} {...bad('size')} />
            </div>
            <div className="ui-field">
              <label className="ui-field__label" htmlFor={`${base}-unit`}>Unit</label>
              <select id={`${base}-unit`} className="ui-input" value={f.unit} onChange={set('unit')}
                {...(f.unit === OTHER ? {} : bad('unit'))}>
                {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
                <option value={OTHER}>Other…</option>
              </select>
            </div>
          </div>
          {f.unit === OTHER && (
            <div className="ui-field">
              <label className="ui-field__label" htmlFor={`${base}-other`}>Unit name</label>
              <input id={`${base}-other`} className="ui-input" autoComplete="off" maxLength={20} placeholder="e.g. rolls"
                value={f.otherUnit} onChange={set('otherUnit')} {...bad('unit')} />
            </div>
          )}
          <div className="ui-field">
            <label className="ui-field__label" htmlFor={`${base}-barcode`}>Barcode</label>
            <div className="pantry-add__typed">
              <input ref={barcodeRef} id={`${base}-barcode`} className="ui-input" inputMode="numeric" autoComplete="off"
                value={f.barcode} onChange={set('barcode')} aria-invalid={error?.field === 'barcode' || undefined}
                aria-describedby={error?.field === 'barcode' ? errId : noCamera ? `${base}-nocam` : undefined} />
              <button type="button" className="btn pantry-add__scan" disabled={!online}
                onClick={() => { setNoCamera(false); setScanning(true) }}>
                <ScanIcon />Scan
              </button>
            </div>
          </div>
          {noCamera && (
            <p id={`${base}-nocam`} className="pantry-add__nocam" role="status">
              <b>Type the barcode instead</b> The camera isn’t available here.
            </p>
          )}
          {error && <p id={errId} className="ui-field__error" role="alert">{error.text}</p>}
        </form>
      </Sheet>
      {scanning && (
        <Suspense fallback={null}>
          <Scanner
            onDetect={(code) => {
              setScanning(false)
              setF((x) => ({ ...x, barcode: code }))
              setError(null)
            }}
            onUnavailable={() => { setScanning(false); setNoCamera(true); barcodeRef.current?.focus() }}
            onClose={() => setScanning(false)} />
        </Suspense>
      )}
    </>
  )
}
