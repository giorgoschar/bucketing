import { expect, it } from 'vitest'
import { stockItem } from '../../../test/fixtures'
import { adjusted, needQty } from './hooks'

// The server sends quantities as JSON numbers (spec §3.2; the B snapshot tests pin it). The optimistic
// stepper does number arithmetic on them: this pins that, so a string ever arriving would show up here first.
it('an optimistic adjust is number arithmetic, clamped at 0 and rounded to cents', () => {
  const up = adjusted(stockItem({ quantity: 2.5, min_quantity: 1 }), 1)
  expect(up.quantity).toBe(3.5)
  expect(typeof up.quantity).toBe('number')
  expect(adjusted(stockItem({ quantity: 0.1, min_quantity: 0 }), 0.2).quantity).toBe(0.3)
  expect(adjusted(stockItem({ quantity: 0.5 }), -1).quantity).toBe(0)
})

it('low and need follow the server rules: low is quantity ≤ min, need is max(1, ceil(2·min − qty))', () => {
  const down = adjusted(stockItem({ quantity: 2, min_quantity: 1, low: false }), -1)
  expect(down).toMatchObject({ quantity: 1, low: true, need_qty: 1 })
  expect(adjusted(stockItem({ quantity: 1, min_quantity: 3 }), -1)).toMatchObject({ quantity: 0, low: true, need_qty: 6 })
  expect(needQty(5, 1)).toBe(1)
  expect(needQty(0.5, 1)).toBe(2)
})
