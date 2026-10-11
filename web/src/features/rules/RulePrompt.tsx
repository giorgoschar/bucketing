import type { QueryClient } from '@tanstack/react-query'
import { toast } from '../../ui/Toast'
import { acceptSuggestion, dismissSuggestion, type RuleSuggestion } from './hooks'

export const promptText = (s: RuleSuggestion) => `Always use ${s.category_name} for ${s.label}?`
export const RULE_SAVED = 'Rule saved. Change it in Settings › Categories.'
const PROMPT_MS = 8000

/** Always: create the rule, then say so. Resolves to the line to show afterwards. */
export async function answerAlways(qc: QueryClient, s: RuleSuggestion): Promise<{ ok: boolean; text: string }> {
  const r = await acceptSuggestion(qc, s)
  return r.ok ? { ok: true, text: RULE_SAVED } : { ok: false, text: r.detail }
}

/** The phone's prompt: the "Saved" toast's question, with its two answers. It goes away with the toast. */
export function showRuleToast(qc: QueryClient, s: RuleSuggestion): void {
  toast(promptText(s), {
    durationMs: PROMPT_MS,
    actions: [
      {
        label: 'Always',
        onClick: () => {
          void answerAlways(qc, s).then((r) => toast(r.text, r.ok ? {} : { tone: 'error' }))
        },
      },
      { label: 'Not now', onClick: () => void dismissSuggestion(s) },
    ],
  })
}

/** The desktop panel's prompt, under its "Saved ·" line. `done` replaces the question with the result. */
export function RulePromptLine({ s, done, onAlways, onNotNow }: {
  s: RuleSuggestion; done: string | null; onAlways: () => void; onNotNow: () => void
}) {
  if (done) return <p className="composer__rule" role="status">{done}</p>
  return (
    <p className="composer__rule" role="group" aria-label="Rule suggestion">
      <span>{promptText(s)}</span>
      <span className="composer__rule-acts">
        <button type="button" className="composer__undo" onClick={onAlways}>Always</button>
        <button type="button" className="composer__undo" onClick={onNotNow}>Not now</button>
      </span>
    </p>
  )
}
