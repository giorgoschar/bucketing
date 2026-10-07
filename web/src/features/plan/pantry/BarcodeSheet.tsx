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
import { type BarcodeProduct, formatQty, sizeLabel } from './types'

export const OFFLINE_WRITE = 'Connect to change the pantry'

type Lookup =
  | { state: 'loading' }
  | { state: 'found'; product: BarcodeProduct }
  | { state: 'missing' }
  | { state: 'unavailable' }
  | { state: 'failed'; message: string }

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
        else if (response.status === 404) done({ state: 'missing' })
        else if (response.status >= 500) done({ state: 'unavailable' })
        else done({ state: 'failed', message: detailOf(error, response.status) })
      },
      () => done({ state: 'unavailable' }),
    )
    return () => ctrl.abort()
  }, [code])

  const title = result.state === 'found' ? result.product.name : `Barcode ${code}`
  const scanAnother = (
    <button type="button" className="btn" onClick={onScanAnother}><ScanIcon />Scan another</button>
  )
  return (
    <Sheet open onClose={onClose} title={title}
      footer={result.state === 'loading' ? undefined : (
        <div className="pantry-sheet__acts">
          {scanAnother}
          {result.state === 'found'
            ? <FoundAction product={result.product} online={online} onAdded={onAdded} onClose={onClose} />
            : <button type="button" className="btn btn--primary" onClick={() => onAddManually(code)}>Add manually</button>}
        </div>
      )}>
      <div className="pantry-lookup" aria-live="polite">
        {result.state === 'loading' && <p className="pantry-lookup__note">Looking up {code}…</p>}
        {result.state === 'found' && <Found product={result.product} code={code} />}
        {result.state === 'missing' && (
          <div className="pantry-lookup__msg">
            <p className="pantry-lookup__head">Not on PosoKanei</p>
            <p className="pantry-lookup__note">Barcode {code} isn’t listed. You can still add it by hand.</p>
          </div>
        )}
        {result.state === 'unavailable' && (
          <div className="pantry-lookup__msg">
            <p className="pantry-lookup__head">Prices unavailable right now</p>
            <p className="pantry-lookup__note">PosoKanei didn’t answer. You can still add it by hand.</p>
          </div>
        )}
        {result.state === 'failed' && (
          <div className="pantry-lookup__msg">
            <p className="pantry-lookup__head">Couldn’t look that up</p>
            <p className="pantry-lookup__note">{result.message}</p>
          </div>
        )}
        {result.state === 'found' && !online && !result.product.in_pantry && <p className="pantry-offline">{OFFLINE_WRITE}</p>}
      </div>
    </Sheet>
  )
}

function Found({ product, code }: { product: BarcodeProduct; code: string }) {
  const priced = product.retailer_prices.filter((r) => r.price != null).sort((a, b) => (a.price as number) - (b.price as number))
  const [best, ...others] = priced
  const size = sizeLabel(product)
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
      {best ? (
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
    </>
  )
}

function FoundAction({ product, online, onAdded, onClose }: {
  product: BarcodeProduct; online: boolean; onAdded: (name: string) => void; onClose: () => void
}) {
  const navigate = useNavigate()
  const add = useAddProduct()
  const [busy, setBusy] = useState(false)
  const have = product.in_pantry
  if (have) {
    return (
      <button type="button" className="btn btn--primary" onClick={() => {
        onClose()
        navigate(`/plan/pantry/${encodeURIComponent(have.stock_item_id)}`)
      }}>Open</button>
    )
  }
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
