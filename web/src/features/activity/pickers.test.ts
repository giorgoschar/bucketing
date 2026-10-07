import { describe, expect, it } from 'vitest'
import { bucketOptions, payerPatch } from './pickers'
import { REF, makeTxn } from './testing'

const values = (r: ReturnType<typeof bucketOptions>) => r.options.map((o) => o.label)

describe('bucket picker (R7)', () => {
  it('a bucketed bill payment keeps a bucket, with the hint', () => {
    const r = bucketOptions(makeTxn({ recurring_bill_id: 'r1', bucket_id: 'b-bills' }), REF)
    expect(values(r)).not.toContain('No bucket (Fixed cost)')
    expect(r.note).toBe('Bill payments keep a bucket. Move the bill instead.')
  })

  it('a bucket-less Fixed cost may stay bucket-less', () => {
    const r = bucketOptions(makeTxn({ recurring_bill_id: 'r1', bucket_id: null }), REF)
    expect(values(r)[0]).toBe('No bucket (Fixed cost)')
  })

  it('income offers No bucket and only income-tracking buckets', () => {
    const r = bucketOptions(makeTxn({ type: 'income', bucket_id: null }), REF)
    expect(values(r)).toEqual(['No bucket', 'Day to day'])
  })

  it('maps the payer choice to paid_by and payer_mode', () => {
    expect(payerPatch('u-maria')).toEqual({ paid_by: 'u-maria', payer_mode: 'single' })
    expect(payerPatch('__own')).toEqual({ paid_by: null, payer_mode: 'own_share' })
  })
})
