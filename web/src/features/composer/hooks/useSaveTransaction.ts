import { useRef, useState } from 'react'
import { type ActionResult, afterTxnWrite, editKey, keys, toast, useAction } from '../bridge'
import { type DefaultsRecord, learn, RULES_API_READY, saveDefaults, shouldOfferRemember } from '../defaults'
import { type CreateBody, toCreateBody, toUpdateBody, type UpdateBody } from '../model'
import type { ComposerState } from '../state'
import type { Txn } from '../types'
import { pendingStore, rowFromBody } from './pendingStore'

export interface SaveCtx { hh: string; householdCurrency: string; fuelCategoryId: string | null; meId: string }
export type SaveOutcome =
  | { status: 'done'; id: string }
  | { status: 'queued' }
  | { status: 'failed'; detail: string }
  | { status: 'busy' }

export function useSaveTransaction(state: ComposerState, ctx: SaveCtx, defaults: DefaultsRecord) {
  const id = state.editId ?? ''
  const create = useAction<CreateBody, Txn>({
    method: 'POST', path: '/api/v1/transactions', body: (b: CreateBody) => b, invalidates: afterTxnWrite,
  })
  const update = useAction<UpdateBody, Txn>({
    method: 'PUT',
    path: `/api/v1/transactions/${id}`,
    body: (b: UpdateBody) => b,
    invalidates: afterTxnWrite,
    pendingId: id,
    // Stays inside `invalidates` (editKey is under transactions.all), so 2a's rollback restores it.
    optimistic: (qc, b) =>
      qc.setQueryData<Txn | null>(editKey(id), (old) =>
        old
          ? {
              ...old,
              amount: Number(b.amount),
              currency: b.currency,
              bucket_id: b.bucket_id ?? null,
              category_id: b.category_id ?? null,
              merchant: b.merchant ?? null,
              notes: b.notes ?? null,
              paid_by: b.paid_by ?? null,
              transaction_date: b.transaction_date ?? old.transaction_date,
            }
          : old,
      ),
  })
  const remove = useAction<void, null>({
    method: 'DELETE',
    path: `/api/v1/transactions/${id}`,
    invalidates: afterTxnWrite,
    pendingId: id,
    toastRejections: false, // a 404 means "already gone"; other rejections are toasted below
    // Queued when offline (spec §5.1). An online failure is ambiguous: if the server applied it, a replay
    // would get 404 and stick in the queue as failed, so roll back and say so instead (like item create).
    queue: 'offline-only',
    optimistic: () => pendingStore.hide(id),
  })
  const rule = useAction<{ pattern: string; category_id: string }>({
    method: 'POST', path: '/api/v1/settings/category-rules', body: (b: { pattern: string; category_id: string }) => b, invalidates: [keys.categoryRules()],
  })

  const busy = useRef(false)
  const [saving, setSaving] = useState(false)
  async function guard(fn: () => Promise<SaveOutcome>): Promise<SaveOutcome> {
    if (busy.current) return { status: 'busy' }
    busy.current = true
    setSaving(true)
    try {
      return await fn()
    } finally {
      busy.current = false
      setSaving(false)
    }
  }
  const outcome = (r: ActionResult<unknown>, knownId?: string): SaveOutcome =>
    r.status === 'done'
      ? { status: 'done', id: knownId ?? (r.data as { id: string }).id }
      : r.status === 'queued'
        ? { status: 'queued' }
        : { status: 'failed', detail: r.detail }

  const saveNew = () =>
    guard(async () => {
      const body = toCreateBody(state, ctx)
      const key = state.clientId ?? ''
      pendingStore.addInFlight(rowFromBody(body, 'sending'))
      try {
        // Spec §4.3: written when Save is tapped, whether the save goes online or is queued.
        await saveDefaults(ctx.hh, learn(defaults, state, ctx))
        const r = outcome(await create.run(body))
        if (r.status === 'done') pendingStore.markJustSaved(r.id)
        if (r.status !== 'failed' && state.rememberRule && state.categoryId && shouldOfferRemember(state, RULES_API_READY)) {
          await rule.run({ pattern: state.merchant.trim(), category_id: state.categoryId })
        }
        return r
      } finally {
        pendingStore.removeInFlight(key)
      }
    })

  const saveEdit = () => guard(async () => outcome(await update.run(toUpdateBody(state, ctx)), id))

  const deleteEntry = () =>
    guard(async () => {
      const r = await remove.run()
      if (r.status === 'rejected' && r.code === 404) return { status: 'done', id }
      if (r.status === 'rejected') {
        pendingStore.unhide(id)
        if (r.code !== 401) toast(r.detail, { tone: 'error' })
      }
      return outcome(r, id)
    })

  return { saveNew, saveEdit, deleteEntry, saving }
}
