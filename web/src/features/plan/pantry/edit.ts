import type { StockEditBody } from './contractTypes'
import { formatQty, num, type StockDetail } from './types'

const BARCODE = /^\d{6,14}$/
export const UNITS = ['g', 'kg', 'ml', 'L', 'pcs'] as const
/** The unit picker's "Other": a free-text unit. */
export const OTHER = 'other'

export interface EditForm { name: string; brand: string; size: string; unit: string; otherUnit: string; barcode: string }

export function initialForm(d: StockDetail): EditForm {
  const known = d.unit != null && (UNITS as readonly string[]).includes(d.unit)
  return {
    name: d.name,
    brand: d.brand ?? '',
    size: d.unit_quantity == null ? '' : formatQty(d.unit_quantity),
    unit: d.unit == null || known ? (d.unit ?? 'g') : OTHER,
    otherUnit: known ? '' : (d.unit ?? ''),
    barcode: d.barcode ?? '',
  }
}

/** The form as a PATCH body of only what changed (C2), or an error to show. */
export function editBody(d: StockDetail, f: EditForm): { body: StockEditBody } | { error: string } {
  const name = f.name.trim()
  if (!name) return { error: 'Give it a name' }
  const size = num(f.size, null)
  if (Number.isNaN(size) || size === 0) return { error: 'Size must be a number above 0' }
  const unit = f.unit === OTHER ? f.otherUnit.trim() : f.unit
  if (size != null && !unit) return { error: 'Give the size a unit' }
  const barcode = f.barcode.trim() || null
  if (barcode != null && !BARCODE.test(barcode)) return { error: 'A barcode is 6 to 14 digits' }

  const body: StockEditBody = {}
  if (name !== d.name) body.name = name
  const brand = f.brand.trim() || null
  if (brand !== (d.brand ?? null)) body.brand = brand
  if (size !== (d.unit_quantity ?? null)) body.unit_quantity = size
  // A size without a unit means nothing: the unit follows the size, and goes when the size is cleared.
  const nextUnit = size == null ? null : unit
  if ((size != null || d.unit_quantity != null) && nextUnit !== (d.unit ?? null)) body.unit = nextUnit
  if (barcode !== (d.barcode ?? null)) body.barcode = barcode
  return { body }
}
