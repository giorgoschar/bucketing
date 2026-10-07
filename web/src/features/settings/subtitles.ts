import type { PushState } from '../../pwa/pushClient'
import type { CategoryItem, HouseholdInfo, NotificationPrefs, Rule, Security, TokenItem } from './hooks'

const n = (count: number, one: string, many = `${one}s`) => `${count} ${count === 1 ? one : many}`

/** The hub's one-line states, from whatever is cached; a missing read gives an empty subtitle. */
export function hubSubtitles(i: {
  security?: Security; household?: HouseholdInfo; categories?: CategoryItem[]; rules?: Rule[]
  tokens?: TokenItem[]; prefs?: NotificationPrefs | null; push: PushState | null
}) {
  const sec = i.security
  const profile = !sec ? '' : [
    sec.totp_enabled ? '2FA on' : '2FA off',
    ...(sec.passkey_available ? [sec.passkey_linked ? 'passkey linked' : 'no passkey'] : []),
  ].join(' · ')
  const household = i.household ? `${i.household.name} · ${n(i.household.members.length, 'member')} · ${i.household.default_currency}` : ''
  const categories = i.categories ? `${n(i.categories.length, 'category', 'categories')}${i.rules ? ` · ${n(i.rules.length, 'rule')}` : ''}` : ''
  const automations = i.tokens ? `Apple Pay Shortcut · ${i.tokens.length ? n(i.tokens.length, 'token') : 'no tokens'}` : 'Apple Pay Shortcut'
  const push = i.push === 'on' ? 'Push on' : 'Push off'
  const alerts = i.prefs ? ` · ${i.prefs.types.filter((t) => t.enabled).length} of ${i.prefs.types.length} alerts` : ''
  return { profile, household, categories, automations, notifications: push + alerts }
}

/** The page's entry script (Vite names it assets/index-<hash>.js in a build). */
const entryScript = () =>
  globalThis.document?.querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/index-"]')?.src ?? ''

/** "Build Ab12Cd" from the hashed entry script name; "Build dev" under the dev server. */
export function buildString(scriptUrl: string = entryScript()): string {
  const m = /index-([A-Za-z0-9_-]+)\.js$/.exec(scriptUrl)
  return `Build ${m ? m[1] : 'dev'}`
}
