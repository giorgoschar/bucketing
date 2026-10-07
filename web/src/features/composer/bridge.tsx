/**
 * The composer's import point for 2a's data layer and kit (2a plan, "Stream A exports"), plus the few
 * helpers 2b adds. Composer files import 2a through here.
 */
import type { QueryKey } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { keys } from '../../data/keys'
import { toast, Toaster } from '../../ui/Toast'

export { type ActionResult, type ActionSpec, useAction } from '../../data/action'
export { type CachedQuery, useCachedQuery } from '../../data/cachedQuery'
export { ApiError, unwrap } from '../../data/http'
export { keys } from '../../data/keys'
export { useOnline } from '../../data/online'
export { toTransactionPage, useBuckets, useCategories, useHousehold } from '../../data/reads'
export type { Bucket, Category, Household, Member, TransactionPage, TransactionRow } from '../../data/types'
export { Badge } from '../../ui/Badge'
export { CheckIcon, ChevronDownIcon, ClockIcon, XIcon } from '../../ui/icons'
export { Segmented } from '../../ui/Segmented'
export { Sheet } from '../../ui/Sheet'
export { toast, Toaster }

export interface ToastInput { text: string; action?: { label: string; onPress: () => void }; durationMs?: number }

const showToast = (t: ToastInput) =>
  toast(t.text, { action: t.action && { label: t.action.label, onClick: t.action.onPress }, durationMs: t.durationMs })

/** 2b's toast shape over 2a's module-level toast(); safe to call after the composer has unmounted. */
export function useComposerToast(): (t: ToastInput) => void {
  return showToast
}

/** A tree plus the toast region (tests, and the full-screen shell). */
export function ToastHost({ children }: { children?: ReactNode }) {
  return (
    <>
      {children}
      <Toaster />
    </>
  )
}

/** Every key a transaction create, edit or delete makes stale (2b spec §5.3). */
export const afterTxnWrite: readonly QueryKey[] = [
  keys.transactions.all, keys.matches(), keys.plan.all, keys.home.all, keys.buckets(), keys.insights.all,
]

/**
 * The full transaction for edit and copy (`null` = the server said 404). Its own key, not
 * `keys.transactions.one(id)`, because that one holds 2c's shape and throws on 404; still under
 * `transactions.all`, so every transaction write refreshes it.
 */
export const editKey = (id: string) => [...keys.transactions.all, 'edit', id] as const

/** Up to 200 recent transactions, for merchant suggestions only. */
export const merchantsKey = [...keys.transactions.all, 'merchants'] as const
