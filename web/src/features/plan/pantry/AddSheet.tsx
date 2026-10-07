import { lazy, Suspense, useEffect, useId, useRef, useState } from 'react'
import { api } from '../../../api/client'
import { useOnline } from '../../../data/online'
import { formatMoney } from '../../../ui/format'
import { CheckIcon, PlusIcon } from '../../../ui/icons'
import { Sheet } from '../../../ui/Sheet'
import { useToast } from '../../../ui/Toast'
import { BarcodeSheet, OFFLINE_WRITE } from './BarcodeSheet'
import { addBodyFor, useAddProduct } from './hooks'
import { ScanIcon, SearchIcon } from './icons'
import { Initial } from './PantryRow'
import { bestPrice, type ProductSummary, sizeLabel } from './types'

/** The camera and its decoder: a separate chunk, fetched only when Scan is tapped (spec §4.3). */
const Scanner = lazy(() => import('./scan/Scanner').then((m) => ({ default: m.Scanner })))

/** PosoKanei search waits this long after the last keystroke (spec §4.3). */
export const SEARCH_DELAY_MS = 300
const MIN_QUERY = 2
const BARCODE = /^\d{6,14}$/
const UNITS = ['g', 'kg', 'ml', 'L', 'pcs'] as const

type Search =
  | { state: 'idle' }
  | { state: 'loading'; q: string }
  | { state: 'done'; q: string; results: ProductSummary[] }
  | { state: 'unavailable'; q: string }

/** "8 Oct" from an ISO date or datetime. */
const shortDate = (iso: string) =>
  new Date(`${iso.slice(0, 10)}T12:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })

const latest = (results: ProductSummary[]): string | null =>
  results.flatMap((p) => p.retailer_prices.map((r) => r.last_updated).filter((d): d is string => !!d))
    .sort().at(-1) ?? null

/** Add to pantry (spec §4.3): search PosoKanei, scan or type a barcode, or add by hand. Online only. */
export function AddSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const online = useOnline()
  const toast = useToast()
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState<Search>({ state: 'idle' })
  const [added, setAdded] = useState<ReadonlySet<string>>(new Set())
  const [manual, setManual] = useState<{ barcode: string | null } | null>(null)
  const [scanning, setScanning] = useState(false)
  const [lookup, setLookup] = useState<string | null>(null)
  const [noCamera, setNoCamera] = useState(false)
  const [typed, setTyped] = useState('')
  const typedRef = useRef<HTMLInputElement>(null)
  const typedId = useId()

  const q = query.trim()
  useEffect(() => {
    if (q.length < MIN_QUERY || !online) return
    const ctrl = new AbortController()
    const timer = setTimeout(() => {
      setSearch({ state: 'loading', q })
      api.GET('/api/v1/products/search', { params: { query: { q } }, signal: ctrl.signal }).then(
        ({ data, response }) => {
          if (ctrl.signal.aborted) return
          setSearch(response.ok ? { state: 'done', q, results: (data as ProductSummary[]) ?? [] } : { state: 'unavailable', q })
        },
        () => { if (!ctrl.signal.aborted) setSearch({ state: 'unavailable', q }) },
      )
    }, SEARCH_DELAY_MS)
    return () => {
      clearTimeout(timer)
      ctrl.abort()
    }
  }, [q, online])
  const shown: Search = q.length < MIN_QUERY ? { state: 'idle' } : search

  // The camera can't be used: say so and put the cursor in the typed-barcode field.
  useEffect(() => { if (noCamera) typedRef.current?.focus() }, [noCamera])

  const add = useAddProduct()
  const addResult = async (p: ProductSummary) => {
    const out = await add(addBodyFor(p))
    if (out.ok) {
      setAdded((s) => new Set(s).add(p.id))
      toast.show(`Added ${p.name}`)
    }
  }

  const lookUp = (code: string) => {
    setNoCamera(false)
    setLookup(code)
  }
  const typedOk = BARCODE.test(typed.trim())

  return (
    <>
      <Sheet open={open} onClose={onClose} title="Add to pantry"
        footer={manual ? <ManualFooter formId="pantry-manual" online={online} /> : undefined}>
        {manual ? (
          <ManualForm id="pantry-manual" barcode={manual.barcode} online={online}
            onBack={() => setManual(null)}
            onAdded={(name) => {
              toast.show(`Added ${name}`)
              onClose()
            }} />
        ) : (
          <div className="pantry-add">
            <label className="pantry-search pantry-search--strong">
              <SearchIcon />
              <input type="search" inputMode="search" enterKeyHint="search" autoComplete="off" placeholder="Search products"
                aria-label="Search PosoKanei" value={query} disabled={!online} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <button type="button" className="btn btn--block pantry-add__scan" disabled={!online}
              onClick={() => { setNoCamera(false); setScanning(true) }}>
              <ScanIcon />Scan barcode
            </button>
            <form className="pantry-add__typed" onSubmit={(e) => { e.preventDefault(); if (typedOk && online) lookUp(typed.trim()) }}>
              <label htmlFor={typedId} className="ui-sr">Type barcode</label>
              <input ref={typedRef} id={typedId} className="ui-input" inputMode="numeric" autoComplete="off" enterKeyHint="search"
                placeholder="Type barcode" value={typed} onChange={(e) => setTyped(e.target.value.replace(/\s/g, ''))}
                aria-describedby={noCamera ? `${typedId}-why` : undefined} />
              <button type="submit" className="btn" disabled={!online || !typedOk}>Look up</button>
            </form>
            {noCamera && (
              <p id={`${typedId}-why`} className="pantry-add__nocam" role="status">
                <b>Type the barcode instead</b> The camera isn’t available here.
              </p>
            )}
            {!online && <p className="pantry-offline">{OFFLINE_WRITE}</p>}
            <SearchResults search={shown} online={online} added={added} onAdd={addResult} />
            <p className="pantry-add__manual">
              Not listed?{' '}
              <button type="button" className="pantry-link" onClick={() => setManual({ barcode: null })}>Add manually</button>
            </p>
          </div>
        )}
      </Sheet>
      {scanning && (
        <Suspense fallback={null}>
          <Scanner
            onDetect={(code) => { setScanning(false); lookUp(code) }}
            onUnavailable={() => { setScanning(false); setNoCamera(true) }}
            onClose={() => setScanning(false)} />
        </Suspense>
      )}
      {lookup && (
        <BarcodeSheet code={lookup} onClose={() => setLookup(null)}
          onScanAnother={() => { setLookup(null); setScanning(true) }}
          onAddManually={(code) => { setLookup(null); setManual({ barcode: code }) }}
          onAdded={(name) => { setLookup(null); toast.show(`Added ${name}`) }} />
      )}
    </>
  )
}

function SearchResults({ search, online, added, onAdd }: {
  search: Search; online: boolean; added: ReadonlySet<string>; onAdd: (p: ProductSummary) => Promise<void>
}) {
  if (search.state === 'idle') return null
  if (search.state === 'loading') return <p className="pantry-add__note" role="status">Searching…</p>
  if (search.state === 'unavailable') {
    return (
      <div className="pantry-lookup__msg" role="status">
        <p className="pantry-lookup__head">Prices unavailable right now</p>
        <p className="pantry-lookup__note">PosoKanei didn’t answer. You can still add it by hand.</p>
      </div>
    )
  }
  const asOf = latest(search.results)
  return (
    <>
      <p className="pantry-add__src">
        <span>Prices from PosoKanei</span>{asOf && <span className="pantry-add__asof"> · Updated {shortDate(asOf)}</span>}
      </p>
      {search.results.length === 0 ? (
        <p className="pantry-add__note">No products match “{search.q}”.</p>
      ) : (
        <ul className="pantry-results" aria-label="Products">
          {search.results.map((p) => <ResultRow key={p.id} p={p} online={online} added={added.has(p.id)} onAdd={onAdd} />)}
        </ul>
      )}
    </>
  )
}

function ResultRow({ p, online, added, onAdd }: {
  p: ProductSummary; online: boolean; added: boolean; onAdd: (p: ProductSummary) => Promise<void>
}) {
  const [busy, setBusy] = useState(false)
  const best = bestPrice(p)
  const sub = [p.brand, sizeLabel(p)].filter(Boolean).join(' · ')
  return (
    <li className="pantry-result" aria-label={p.name}>
      <Initial name={p.name} />
      <span className="pantry-result__main">
        <span className="pantry-result__name">{p.name}</span>
        {sub && <span className="pantry-result__sub">{sub}</span>}
      </span>
      {best && (
        <span className="pantry-result__end">
          <span className="ui-num">{formatMoney(best.price as number)}</span>
          <span className="pantry-result__store">{best.display_name}</span>
        </span>
      )}
      <button type="button" className={`ui-iconbtn pantry-result__add${added ? ' is-added' : ''}`}
        aria-label={added ? `Added ${p.name}` : `Add ${p.name}`} disabled={!online || busy || added}
        onClick={async () => {
          setBusy(true)
          await onAdd(p)
          setBusy(false)
        }}>
        {added ? <CheckIcon /> : <PlusIcon />}
      </button>
    </li>
  )
}

/** "1,5" or "1.5" → 1.5; blank → the fallback; anything else → NaN. */
function num(text: string, blank: number | null): number | null {
  const s = text.trim().replace(',', '.')
  if (s === '') return blank
  return /^\d+(\.\d+)?$/.test(s) ? Number(s) : NaN
}

function ManualFooter({ formId, online }: { formId: string; online: boolean }) {
  return (
    <div className="pantry-sheet__foot">
      {!online && <p className="pantry-offline">{OFFLINE_WRITE}</p>}
      <button type="submit" form={formId} className="btn btn--primary btn--block btn--lg" disabled={!online}>
        <PlusIcon />Add to pantry
      </button>
    </div>
  )
}

function ManualForm({ id, barcode, online, onBack, onAdded }: {
  id: string; barcode: string | null; online: boolean; onBack: () => void; onAdded: (name: string) => void
}) {
  const add = useAddProduct()
  const base = useId()
  const [f, setF] = useState({ name: '', brand: '', size: '', unit: 'g', quantity: '1', min: '1' })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }))
  const nameRef = useRef<HTMLInputElement>(null)
  useEffect(() => { nameRef.current?.focus() }, [])

  const submit = async () => {
    const name = f.name.trim()
    const size = num(f.size, null)
    const quantity = num(f.quantity, 0)
    const min = num(f.min, 1)
    if (!name) return setError('Give it a name')
    if (Number.isNaN(size) || Number.isNaN(quantity) || Number.isNaN(min)) return setError('Size and amounts must be numbers')
    if (!online || busy) return
    setError(null)
    setBusy(true)
    const out = await add({
      name, brand: f.brand.trim() || null, unit_quantity: size, unit: size == null ? null : f.unit,
      quantity: quantity as number, min_quantity: min as number, barcode,
    })
    setBusy(false)
    if (out.ok) onAdded(name)
    else if (out.kind === 'rejected') setError(out.message)
  }

  const field = (k: 'name' | 'brand', label: string, extra: object = {}) => (
    <div className="ui-field">
      <label className="ui-field__label" htmlFor={`${base}-${k}`}>{label}</label>
      <input id={`${base}-${k}`} className="ui-input" value={f[k]} onChange={set(k)} autoComplete="off" {...extra} />
    </div>
  )
  const amount = (k: 'size' | 'quantity' | 'min', label: string) => (
    <div className="ui-field">
      <label className="ui-field__label" htmlFor={`${base}-${k}`}>{label}</label>
      <input id={`${base}-${k}`} className="ui-input" inputMode="decimal" autoComplete="off" value={f[k]} onChange={set(k)} />
    </div>
  )
  return (
    <form id={id} className="pantry-manual" noValidate onSubmit={(e) => { e.preventDefault(); void submit() }}>
      {barcode && <p className="pantry-lookup__note">Barcode {barcode}</p>}
      {field('name', 'Name', { ref: nameRef, maxLength: 200, 'aria-invalid': error === 'Give it a name' || undefined })}
      {field('brand', 'Brand', { maxLength: 120 })}
      <div className="pantry-manual__size">
        {amount('size', 'Size')}
        <div className="ui-field">
          <label className="ui-field__label" htmlFor={`${base}-unit`}>Unit</label>
          <select id={`${base}-unit`} className="ui-input" value={f.unit} onChange={set('unit')}>
            {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
      </div>
      <div className="pantry-manual__size">
        {amount('quantity', 'In stock')}
        {amount('min', 'Keep at least')}
      </div>
      {error && <p className="ui-field__error" role="alert">{error}</p>}
      <button type="button" className="pantry-link pantry-manual__back" onClick={onBack}>Search PosoKanei instead</button>
    </form>
  )
}
