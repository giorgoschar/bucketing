import { ToggleRow } from '../../../ui/ToggleRow'
import type { Category } from '../bridge'
import { shouldOfferRemember } from '../defaults'
import type { ComposerState } from '../state'
import './scan.css'

const ReceiptIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9} strokeLinecap="round" strokeLinejoin="round"
    aria-hidden="true" focusable="false" className="ui-icon">
    <path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z" />
    <path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8" /><path d="M12 17.5v-11" />
  </svg>
)

export interface ReviewBannerProps {
  s: ComposerState
  categories: Category[]
  rulesReady: boolean
  onRemember: (on: boolean) => void
}

/** After a scan (spec §4.7): where the values came from, and the offer to remember a corrected category. */
export function ReviewBanner({ s, categories, rulesReady, onRemember }: ReviewBannerProps) {
  if (s.source === 'manual') return null
  const category = categories.find((c) => c.id === s.categoryId)
  return (
    <div className="review">
      <p className="review__banner" role="status">
        <ReceiptIcon />
        {s.source === 'qr' ? 'Read from myDATA QR' : 'Receipt attached. Type the details.'}
      </p>
      {shouldOfferRemember(s, rulesReady) && category && (
        <div className="review__remember">
          <ToggleRow label={`Remember "${s.merchant.trim()}" → "${category.name}"`} hint="Next time this shop gets this category"
            checked={s.rememberRule} onChange={onRemember} />
        </div>
      )}
    </div>
  )
}
