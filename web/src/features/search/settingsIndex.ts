export interface SettingsPage { title: string; to: string; keywords: string[] }

/** Every settings page (router.tsx) with the words people use for what is on it. */
export const SETTINGS_PAGES: SettingsPage[] = [
  { title: 'Profile & security', to: '/settings/profile', keywords: ['profile', 'name', 'email', 'password', 'passkey', 'security', 'two-factor', '2fa', 'avatar', 'sign out'] },
  { title: 'Household', to: '/settings/household', keywords: ['household', 'members', 'invite', 'partner', 'currency', 'family'] },
  { title: 'Categories & rules', to: '/settings/categories', keywords: ['categories', 'category', 'rules', 'rule', 'merchant', 'colour', 'color'] },
  { title: 'Automations', to: '/settings/automations', keywords: ['automations', 'token', 'tokens', 'apple pay', 'shortcut', 'api'] },
  { title: 'Notifications', to: '/settings/notifications', keywords: ['notifications', 'alerts', 'push', 'reminders', 'digest'] },
  { title: 'Appearance', to: '/settings/appearance', keywords: ['appearance', 'dark', 'light', 'theme', 'mode', 'system'] },
]
