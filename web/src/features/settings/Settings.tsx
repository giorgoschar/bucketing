import { Link } from 'react-router'
import { usePushState } from '../../pwa/pushClient'
import { useSession } from '../../session/SessionProvider'
import { avatarLook } from '../../shell/avatar'
import { THEME_LABELS, useTheme } from '../../shell/theme'
import { BackHeader } from '../../ui/BackHeader'
import { ChevronRightIcon } from '../../ui/icons'
import { useCategories, useHousehold, useNotificationPrefs, useProfile, useRules, useSecurity, useTokens } from './hooks'
import { buildString, hubSubtitles } from './subtitles'
import './settings.css'

const ROWS = [
  { key: 'profile', title: 'Profile & security', to: '/settings/profile' },
  { key: 'household', title: 'Household', to: '/settings/household' },
  { key: 'categories', title: 'Categories & rules', to: '/settings/categories' },
  { key: 'automations', title: 'Automations', to: '/settings/automations' },
  { key: 'notifications', title: 'Notifications', to: '/settings/notifications' },
  { key: 'appearance', title: 'Appearance', to: '/settings/appearance' },
] as const

/** A short hub; subtitles come from cached queries, so it works offline. */
export function Settings() {
  const { me, signOut } = useSession()
  const profile = useProfile().data
  const theme = useTheme()
  const subs = {
    ...hubSubtitles({
      security: useSecurity().data,
      household: useHousehold().data,
      categories: useCategories().data,
      rules: useRules().data,
      tokens: useTokens().data,
      prefs: useNotificationPrefs().data,
      push: usePushState().state,
    }),
    appearance: THEME_LABELS[theme],
  }
  const name = profile?.display_name || me?.display_name || me?.username || ''
  const email = profile?.email ?? me?.email ?? null
  const avatar = avatarLook(profile?.avatar_color, 'avatar--lg')
  return (
    <>
      <BackHeader title="Settings" back="/" />
      <section className="screen settings">
        <Link to="/settings/profile" className="ui-card settings__who" aria-label={`Your profile: ${name}`}>
          <span className={avatar.className} style={avatar.style} aria-hidden="true">
            {name.slice(0, 1).toUpperCase()}
          </span>
          <span className="settings__whotext">
            <span className="settings__name">{name}</span>
            {email && <span className="settings__sub">{email}</span>}
          </span>
          <ChevronRightIcon />
        </Link>
        <nav className="ui-list settings__list" aria-label="Settings">
          {ROWS.map((r) => (
            <Link key={r.key} to={r.to} className="ui-row settings__row">
              <span className="ui-row__main">
                <span className="ui-row__title">{r.title}</span>
                {subs[r.key] && <span className="ui-row__sub">{subs[r.key]}</span>}
              </span>
              <span className="settings__chev"><ChevronRightIcon /></span>
            </Link>
          ))}
        </nav>
        <button type="button" className="btn btn--danger btn--block" onClick={() => void signOut()}>Sign out</button>
        <p className="settings__build">{buildString()}</p>
      </section>
    </>
  )
}
