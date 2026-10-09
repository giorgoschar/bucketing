import { useSyncExternalStore } from 'react'

/** Settings › Appearance (polish A3): System follows the phone; Light and Dark pin this device. */
export type ThemeChoice = 'system' | 'light' | 'dark'

/** Per device, never synced: two people on one household can each keep their own.
 *  public/theme-boot.js (the before-first-paint boot, a plain file) repeats this key and THEME_COLORS. */
export const THEME_KEY = 'tameio.theme'
/** The page background (--bg) of each theme, which is also the status bar colour (theme-color). */
export const THEME_COLORS = { light: '#EEF1F7', dark: '#090B10' } as const

const CHOICES: readonly ThemeChoice[] = ['system', 'light', 'dark']

/** The saved choice; System when nothing is saved, the value is unknown, or storage throws (private mode). */
export function readTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return CHOICES.includes(v as ThemeChoice) ? (v as ThemeChoice) : 'system'
  } catch {
    return 'system'
  }
}

/** Save the choice (System removes the key). A storage that throws only loses the memory, never the tap. */
export function saveTheme(choice: ThemeChoice): void {
  try {
    if (choice === 'system') localStorage.removeItem(THEME_KEY)
    else localStorage.setItem(THEME_KEY, choice)
  } catch {
    // Private mode or blocked storage: the choice still applies until the app closes.
  }
}

/** data-theme on <html> (tokens.css lets it win over prefers-color-scheme), and the status bar colour.
 *  index.html carries one theme-color per OS scheme; a pinned theme sets both, System gives them back. */
export function applyTheme(choice: ThemeChoice, doc: Document = document): void {
  const root = doc.documentElement
  if (choice === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', choice)
  for (const meta of doc.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')) {
    const own = (meta.getAttribute('media') ?? '').includes('light') ? THEME_COLORS.light : THEME_COLORS.dark
    meta.content = choice === 'system' ? own : THEME_COLORS[choice]
  }
}

const listeners = new Set<() => void>()
let current: ThemeChoice = 'system'

/** Run from main.tsx before createRoot: it sets the store's value for the Appearance screen and re-applies
 *  the theme. public/theme-boot.js has already applied it from <head>, before the first paint. */
export function bootTheme(): void {
  current = readTheme()
  applyTheme(current)
}

/** Choose, save and apply at once. */
export function setTheme(choice: ThemeChoice): void {
  current = choice
  saveTheme(choice)
  applyTheme(choice)
  listeners.forEach((l) => l())
}

const subscribe = (cb: () => void) => {
  listeners.add(cb)
  return () => { listeners.delete(cb) }
}

/** The current choice for the Appearance screen (and the Settings hub subtitle). */
export function useTheme(): ThemeChoice {
  return useSyncExternalStore(subscribe, () => current, () => current)
}

export const THEME_LABELS: Record<ThemeChoice, string> = { system: 'System', light: 'Light', dark: 'Dark' }
