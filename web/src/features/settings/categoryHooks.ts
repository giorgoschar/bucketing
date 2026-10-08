import { useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { insightsKeys, settingsKeys } from '../../data/keys'
import { type OnlineOutcome, runOnline, useOnlineAction } from '../../data/onlineAction'
import type { RawResult } from '../../data/rawJson'
import { useSession } from '../../session/SessionProvider'
import { useToast } from '../../ui/Toast'
import type { CategoryItem, Rule } from './hooks'

export const ruleChip = (r: { pattern: string; match_count: number }) => `${r.pattern} ${r.match_count}`
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
export const deleteMessage = (c: CategoryItem) =>
  `${plural(c.expense_count ?? 0, 'expense', 'expenses')} will become uncategorised and its ${plural(c.rule_count ?? 0, 'rule', 'rules')} will be deleted.`

export interface CategoryBody { name: string; color: string; icon: string }

/** Category and rule writes: online only; every one refreshes categories, rules and Insights. */
export function useCategoryActions() {
  const act = useOnlineAction()
  const qc = useQueryClient()
  const toast = useToast()
  const hh = useSession().me?.household_id ?? ''
  const keys = [settingsKeys.categories(hh), settingsKeys.rules(hh), insightsKeys.all(hh)]
  const refresh = () => Promise.all(keys.map((queryKey) => qc.invalidateQueries({ queryKey })))
  return {
    create: (body: CategoryBody) => act(() => api.POST('/api/v1/settings/categories', { body }), { invalidates: keys, success: 'Category added' }),
    update: (id: string, body: CategoryBody) =>
      act(() => api.PUT('/api/v1/settings/categories/{category_id}', { params: { path: { category_id: id } }, body }), { invalidates: keys, success: 'Saved' }),
    remove: (id: string) =>
      act(() => api.DELETE('/api/v1/settings/categories/{category_id}', { params: { path: { category_id: id } } }), { invalidates: keys, success: 'Category deleted' }),
    /** POST (an upsert by pattern) for a new rule, PUT for an edit. 400/409 come back for the field. */
    saveRule: async (rule: { id?: string; pattern: string; category_id: string }): Promise<OnlineOutcome<Rule>> => {
      const body = { pattern: rule.pattern, category_id: rule.category_id }
      const out = await runOnline(() =>
        (rule.id
          ? api.PUT('/api/v1/settings/category-rules/{rule_id}', { params: { path: { rule_id: rule.id } }, body })
          : api.POST('/api/v1/settings/category-rules', { body })) as Promise<RawResult<Rule>>,
      )
      if (out.ok) await refresh()
      else if (out.kind === 'offline' || out.kind === 'rate') toast.show(out.message, { tone: 'error' })
      return out
    },
    deleteRule: (id: string) =>
      act(() => api.DELETE('/api/v1/settings/category-rules/{rule_id}', { params: { path: { rule_id: id } } }), { invalidates: keys, success: 'Rule deleted' }),
  }
}
