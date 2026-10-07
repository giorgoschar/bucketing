import { expect, it } from 'vitest'
import { day, entry } from '../../test/fixtures'
import type { UpcomingDayOut } from '../../data/types'
import { applyChange, patchUpcoming } from './entryPatch'

const cosmote = entry() // out, €38.90, due 2026-10-09
const days = [
  day('2026-10-08', [], 1000),
  day('2026-10-09', [cosmote], 961.1),
  day('2026-11-02', [entry({ id: 'e2', due_date: '2026-11-02', amount: 50 })], -50),
]
const nets = (d: UpcomingDayOut[]) => d.map((x) => x.net_this_month)

it('skip gives the expected amount back from the due day to the end of its month', () => {
  const out = patchUpcoming(days, cosmote, { kind: 'skip' })
  expect(nets(out)).toEqual([1000, 1000, -50])
  expect(out[1].entries[0].status).toBe('skipped')
})

it('paid today with another amount: the paid amount counts from today, the expected one goes', () => {
  const out = patchUpcoming(days, cosmote, { kind: 'done', amount: 40, today: '2026-10-08' })
  expect(nets(out)).toEqual([960, 960, -50])
  expect(out[1].entries[0]).toMatchObject({ status: 'done', amount: 40, estimated: false })
})

it('a new amount moves only its own month, from the due day', () => {
  expect(nets(patchUpcoming(days, cosmote, { kind: 'amount', amount: 50 }))).toEqual([1000, 950, -50])
})

it('in entries add instead of subtract, and the next month restarts', () => {
  const salary = entry({ id: 's', direction: 'in', amount: 1500, due_date: '2026-10-26' })
  const d = [day('2026-10-26', [salary], 2500), day('2026-10-30', [], 2400), day('2026-11-01', [], 0)]
  expect(nets(patchUpcoming(d, salary, { kind: 'skip' }))).toEqual([1000, 900, 0])
})

it('a confirmed match is done without counting the money twice', () => {
  expect(nets(patchUpcoming(days, cosmote, { kind: 'linked' }))).toEqual([1000, 1000, -50])
  expect(applyChange(cosmote, { kind: 'linked' }).status).toBe('done')
})

it('a variable entry (amount null) counts as zero, never NaN', () => {
  const variable = entry({ amount: null })
  const out = patchUpcoming([day('2026-10-09', [variable], 100)], variable, { kind: 'amount', amount: 80 })
  expect(out[0].net_this_month).toBe(20)
})
