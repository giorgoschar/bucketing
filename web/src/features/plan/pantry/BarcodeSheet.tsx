import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { api } from '../../../api/client'
import { detailOf } from '../../../data/http'
import { useOnline } from '../../../data/online'
import { formatMoney } from '../../../ui/format'
import { PlusIcon } from '../../../ui/icons'
import { Sheet } from '../../../ui/Sheet'
import { addBodyFor, useAddProduct } from './hooks'
import { ScanIcon } from './icons'
import { Initial } from './PantryRow'
import { type BarcodeLookupError, type BarcodeProduct, formatQty, sizeLabel } from './types'

export const OFFLINE_WRITE = 'Connect to change the pantry'

type InPantry = NonNullable<BarcodeProduct['in_pantry']>

/** `missing` (404) and `unavailable` (503) still say whether the household has this barcode (pantry I3). */
type Lookup =
  | { state: 'loading' }
  | { state: 'found'; product: BarcodeProduct }
  | { state: 'missing'; inPantry: InPantry | null }
  | { state: 'unavailable'; inPantry: InPantry | null }
  | { state: 'failed'; message: string }

/** The pantry match in a 404/503 body ({detail, in_pantry}); null for any other shape. */
function inPantryOf(error: unknown): InPantry | null {
  const match = typeof error === 'object' && error !== null ? (error as Partial<BarcodeLookupError>).in_pantry : null
  return match && typeof match.stock_item_id === 'string' ? match : null
}

export interface BarcodeSheetProps {
  code: string
  onClose: () => void
  onScanAnother: () => void
  onAddManually: (code: string) => void
  /** The product was added to the pantry. */
  onAdded: (name: string) => void
}

/** What a barcode is (pantry spec §4.3): its best price, the other stores, and whether it's in the pantry. */
export function BarcodeSheet({ code, onClose, onScanAnother, onAddManually, onAdded }: BarcodeSheetProps) {
  const online = useOnline()
  const [lookup, setLookup] = useState<{ code: string; result: Lookup }>({ code, result: { state: 'loading' } })
  const result: Lookup = lookup.code === code ? lookup.result : { state: 'loading' }

  useEffect(() => {
    const ctrl = new AbortController()
    const done = (r: Lookup) => { if (!ctrl.signal.aborted) setLookup({ code, result: r }) }
    api.GET('/api/v1/products/barcode/{code}', { params: { path: { code } }, signal: ctrl.signal }).then(
      ({ data, error, response }) => {
        if (response.ok) done({ state: 'found', product: data as BarcodeProduct })
        else if (response.status === 404) done({ state: 'missing', inPantry: inPantryOf(error) })
        else if (response.status >= 500) done({ state: 'unavailable', inPantry: inPantryOf(error) })
        else done({ state: 'failed', message: detailOf(error, response.status) })
      },
      () => done({ state: 'unavailable', inPantry: null }),
    )
    return () => ctrl.abort()
  }, [code])

  const title = result.state === 'found' ? result.product.name : `Barcode ${code}`
  const missHave = result.state === 'missing' || result.state === 'unavailable' ? result.inPantry : null
  const have = missHave && <> · <b className="pantry-lookup__have">In pantry: {formatQty(missHave.quantity)}</b></>
  const scanAnother = (
    <button type="button" className="btn" disabled={!online} onClick={onScanAnother}><ScanIcon />Scan another</button>
  )
  return (
    <Sheet open onClose={onClose} title={title}
      footer={result.state === 'loading' ? undefined : (
        <div className="pantry-sheet__acts">
          {scanAnother}
          {result.state === 'found'
            ? <FoundAction product={result.product} online={online} onAdded={onAdded} onClose={onClose} />
            : missHave
              ? <OpenButton item={missHave} onClose={onClose} />
              : <button type="button" className="btn btn--primary" onClick={() => onAddManually(code)}>Add manually</button>}
        </div>
      )}>
      <div className="pantry-lookup" aria-live="polite">
        {result.state === 'loading' && <p className="pantry-lookup__note">Looking up {code}…</p>}
        {result.state === 'found' && <Found product={result.product} code={code} />}
        {result.state === 'missing' && (
          <div className="pantry-lookup__msg">
            <p className="pantry-lookup__head">Not on PosoKanei</p>
            <p className="pantry-lookup__note">
              {missHave ? <>Barcode <span className="ui-num">{code}</span> isn’t listed{have}</>
                : <>Barcode {code} isn’t listed. You can still add it by hand.</>}
            </p>
          </div>
        )}
        {result.state === 'unavailable' && (
          <div className="pantry-lookup__msg">
            <p className="pantry-lookup__head">Prices unavailable right now</p>
            <p className="pantry-lookup__note">
              {missHave ? <>PosoKanei didn’t answer. Barcode <span className="ui-num">{code}</span>{have}</>
                : <>PosoKanei didn’t answer. You can still add it by hand.</>}
            </p>
          </div>
        )}
        {result.state === 'failed' && (
          <div className="pantry-lookup__msg">
            <p className="pantry-lookup__head">Couldn’t look that up</p>
            <p className="pantry-lookup__note">{result.message}</p>
          </div>
        )}
        {result.state !== 'loading' && !online && <p className="pantry-offline">{OFFLINE_WRITE}</p>}
      </div>
    </Sheet>
  )
}

function Found({ product, code }: { product: BarcodeProduct; code: string }) {
  const priced = product.retailer_prices.filter((r) => r.price != null).sort((a, b) => (a.price as number) - (b.price as number))
  const [best, ...others] = priced
  const size = sizeLabel(product)
  const fromOff = product.source === 'openfoodfacts'
  return (
    <>
      <div className="pantry-lookup__who">
        <Initial name={product.name} size="lg" />
        <div className="pantry-lookup__id">
          {(product.brand || size) && <p className="pantry-lookup__brand">{[product.brand, size].filter(Boolean).join(' · ')}</p>}
          <p className="pantry-lookup__note">
            Barcode <span className="ui-num">{product.barcode ?? code}</span>
            {product.in_pantry && <> · <b className="pantry-lookup__have">In pantry: {formatQty(product.in_pantry.quantity)}</b></>}
          </p>
        </div>
      </div>
      {fromOff ? (
        <p className="pantry-lookup__note">No prices for this product yet</p>
      ) : best ? (
        <div className="pantry-best">
          <div>
            <p className="pantry-best__label">Best price</p>
            <p className="pantry-best__fig">
              <span className="ui-num pantry-best__price">{formatMoney(best.price as number)}</span> at {best.display_name}
            </p>
          </div>
          {best.is_discount && <span className="ui-badge ui-badge--pos">On offer</span>}
        </div>
      ) : (
        <p className="pantry-lookup__note">No store has a price for it today.</p>
      )}
      {others.length > 0 && (
        <p className="pantry-lookup__others">
          {others.map((r, i) => (
            <span key={r.retailer}>{i > 0 && ' · '}{r.display_name} <span className="ui-num">{formatMoney(r.price as number)}</span></span>
          ))}
        </p>
      )}
      {fromOff && (
        <p className="pantry-lookup__note pantry-lookup__credit">
          Product data: <a href="https://world.openfoodfacts.org" target="_blank" rel="noopener noreferrer">Open Food Facts</a>
        </p>
      )}
    </>
  )
}

/** Open: the barcode is already in the pantry, so go to that item instead of adding it again. */
function OpenButton({ item, onClose }: { item: InPantry; onClose: () => void }) {
  const navigate = useNavigate()
  return (
    <button type="button" className="btn btn--primary" onClick={() => {
      onClose()
      navigate(`/plan/pantry/${encodeURIComponent(item.stock_item_id)}`)
    }}>Open</button>
  )
}

function FoundAction({ product, online, onAdded, onClose }: {
  product: BarcodeProduct; online: boolean; onAdded: (name: string) => void; onClose: () => void
}) {
  const add = useAddProduct()
  const [busy, setBusy] = useState(false)
  if (product.in_pantry) return <OpenButton item={product.in_pantry} onClose={onClose} />
  return (
    <button type="button" className="btn btn--primary" disabled={!online || busy} onClick={async () => {
      setBusy(true)
      const out = await add(addBodyFor(product))
      setBusy(false)
      if (out.ok) onAdded(product.name)
    }}>
      <PlusIcon />Add to pantry
    </button>
  )
}
