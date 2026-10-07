import type { QueryClient } from '@tanstack/react-query'
import { keys } from '../../data/keys'
import type { EntryOut, RecurringItemOut, UpcomingDayOut } from '../../data/types'

export type EntryChange =
  /** Paid / Received: creates a transaction dated on the entry's due day (as the server does). */
  | { kind: 'done'; amount: number | null; today: string }
  /** A confirmed match: done, and its transaction already counts. */
  | { kind: 'linked' }
  | { kind: 'skip' }
  | { kind: 'amount'; amount: number }
  | { kind: 'undo' }

const signed = (e: EntryOut, amount: number | null) => (amount ?? 0) * (e.direction === 'in' ? 1 : -1)
const cents = (n: number) => Math.round(n * 100) / 100
const monthOf = (iso: string) => iso.slice(0, 7)

export function applyChange(e: EntryOut, change: EntryChange): EntryOut {
  switch (change.kind) {
    case 'done': return { ...e, status: 'done', amount: change.amount ?? e.amount, estimated: false, overdue: false }
    case 'linked': return { ...e, status: 'done', overdue: false }
    case 'skip': return { ...e, status: 'skipped', overdue: false }
    case 'amount': return { ...e, amount: change.amount, estimated: false }
    case 'undo': return { ...e, status: 'expected' }
  }
}

/** How a change moves the running "net this month" shown on `day` (planning spec §5.2). */
export function netDelta(day: string, target: EntryOut, change: EntryChange): number {
  const expected = signed(target, target.amount)
  // An expected entry counts from its due day to the end of its own month.
  const counted = monthOf(day) === monthOf(target.due_date) && day >= target.due_date
  switch (change.kind) {
    case 'skip':
    case 'linked':
      return counted ? -expected : 0
    case 'amount':
      return counted ? signed(target, change.amount) - expected : 0
    case 'done': {
      // The new transaction is dated on the due day and the server seeds this month's net with the
      // whole month, so it counts on every listed day of today's month when it is due this month.
      const thisMonth = monthOf(change.today)
      const paid = monthOf(day) === thisMonth && monthOf(target.due_date) === thisMonth
        ? signed(target, change.amount ?? target.amount) : 0
      return paid - (counted ? expected : 0)
    }
    case 'undo':
      return 0 // the refetch after the action settles the figures
  }
}

export function patchUpcoming(days: UpcomingDayOut[], target: EntryOut, change: EntryChange): UpcomingDayOut[] {
  return days.map((d) => ({
    ...d,
    net_this_month: cents(d.net_this_month + netDelta(d.date, target, change)),
    entries: d.entries.map((e) => (e.id === target.id ? applyChange(e, change) : e)),
  }))
}

/** The optimistic patch for an entry action, on every cached list that shows the entry (all under affects.entry). */
export function patchEntryEverywhere(qc: QueryClient, target: EntryOut, change: EntryChange): void {
  qc.setQueriesData<UpcomingDayOut[]>({ queryKey: [...keys.plan.all, 'upcoming'] }, (old) =>
    old && patchUpcoming(old, target, change))
  qc.setQueriesData<EntryOut[]>({ queryKey: [...keys.home.all, 'overdue'] }, (old) =>
    old?.map((e) => (e.id === target.id ? applyChange(e, change) : e)))
  qc.setQueryData<RecurringItemOut[]>(keys.recurring.list(), (old) =>
    old?.map((i) => (i.next_entry && i.next_entry.id === target.id ? { ...i, next_entry: applyChange(i.next_entry, change) } : i)))
}
