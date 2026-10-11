import type { QueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import type { components } from '../../api/schema'
import { detailOf } from '../../data/http'
import { keys } from '../../data/keys'
import { isOnline } from '../../data/online'

export type RuleSuggestion = components['schemas']['RuleSuggestionOut']

export const SUGGESTION_PATH = '/api/v1/category-rules/suggestion'
export const DISMISS_PATH = '/api/v1/category-rules/suggestion/dismiss'
const ASK_TIMEOUT_MS = 8000

/**
 * Should this saved entry offer a rule? `null` for no, for offline, and for any failure: the prompt is a courtesy and
 * never an error. Call it only for an entry that reached the server (not a queued one).
 */
export async function askForSuggestion(transactionId: string): Promise<RuleSuggestion | null> {
  if (!isOnline()) return null
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), ASK_TIMEOUT_MS)
  try {
    const { data, response } = await api.GET(SUGGESTION_PATH, { params: { query: { transaction_id: transactionId } }, signal: ctrl.signal })
    return response.ok ? (data ?? null) : null
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

/** "Always": the rule is created, or re-pointed if the pattern had another category. true when the server took it. */
export async function acceptSuggestion(qc: QueryClient, s: RuleSuggestion): Promise<{ ok: true } | { ok: false; detail: string }> {
  try {
    const { error, response } = await api.POST('/api/v1/settings/category-rules', { body: { pattern: s.pattern, category_id: s.category_id } })
    if (!response.ok) return { ok: false, detail: detailOf(error, response.status) }
    void qc.invalidateQueries({ queryKey: keys.categoryRules() })
    return { ok: true }
  } catch {
    return { ok: false, detail: 'Couldn’t save the rule. Try again.' }
  }
}

/** "Not now": counts towards the server's two-strikes rule. Fire and forget. */
export async function dismissSuggestion(s: RuleSuggestion): Promise<void> {
  try {
    await api.POST(DISMISS_PATH, { body: { pattern: s.pattern } })
  } catch {
    // Nothing to tell the user: the prompt was already gone.
  }
}
