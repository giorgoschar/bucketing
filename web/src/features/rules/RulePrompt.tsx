import type { QueryClient } from '@tanstack/react-query'
import { amendToast, toast } from '../../ui/Toast'
import { acceptSuggestion, dismissSuggestion, type RuleSuggestion } from './hooks'

export const promptText = (s: RuleSuggestion) => `Always use ${s.category_name} for ${s.label}?`
export const RULE_SAVED = 'Rule saved. Change it in Settings › Categories.'
const PROMPT_MS = 8000

/** Always: create the rule, then say so. Resolves to the line to show afterwards. */
export async function answerAlways(qc: QueryClient, s: RuleSuggestion): Promise<{ ok: boolean; text: string }> {
  const r = await acceptSuggestion(qc, s)
  return r.ok ? { ok: true, text: RULE_SAVED } : { ok: false, text: r.detail }
}

/**
 * The phone's prompt: the question is added to the "Saved" toast itself (id `toastId`), next to its own action (Undo).
 * Only while that toast is still on screen: if it expired, was undone or was replaced, nothing is shown (ignoring a
 * prompt counts as nothing, and the server offers it again next time). Never touches a different toast.
 */
export function amendSavedToast(qc: QueryClient, toastId: number, base: { text: string; action?: { label: string; onPress: () => void } }, s: RuleSuggestion): boolean {
  return amendToast(toastId, {
    message: `${base.text} · ${promptText(s)}`,
    durationMs: PROMPT_MS,
    actions: [
      {
        label: 'Always',
        onClick: () => {
          void answerAlways(qc, s).then((r) => toast(r.text, r.ok ? {} : { tone: 'error' }))
        },
      },
      { label: 'Not now', onClick: () => void dismissSuggestion(s) },
      // Undo last: it stays where it was, in the bottom-right corner.
      ...(base.action ? [{ label: base.action.label, onClick: base.action.onPress }] : []),
    ],
  })
}

/** The desktop panel's prompt, under its "Saved ·" line. `done` replaces the question with the result. */
export function RulePromptLine({ s, done, onAlways, onNotNow }: {
  s: RuleSuggestion; done: { ok: boolean; text: string } | null; onAlways: () => void; onNotNow: () => void
}) {
  // A saved rule replaces the question; a failed one is shown in the error style and the question stays for a retry.
  if (done?.ok) return <p className="composer__rule" role="status">{done.text}</p>
  return (
    <div role="status">
    {done && <p className="composer__rule composer__rule--fail">{done.text}</p>}
    <p className="composer__rule" role="group" aria-label="Rule suggestion">
      <span>{promptText(s)}</span>
      <span className="composer__rule-acts">
        <button type="button" className="composer__undo" onClick={onAlways}>Always</button>
        <button type="button" className="composer__undo" onClick={onNotNow}>Not now</button>
      </span>
    </p>
    </div>
  )
}
