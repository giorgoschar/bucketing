import { BackHeader } from '../../ui/BackHeader'
import { Segmented } from '../../ui/Segmented'
import { THEME_LABELS, type ThemeChoice, setTheme, useTheme } from '../../shell/theme'
import './settings.css'

const OPTIONS = (['system', 'light', 'dark'] as const).map((value) => ({ value, label: THEME_LABELS[value] }))

/** Settings › Appearance: System / Light / Dark, for this device only. Applies at once, works offline. */
export function Appearance() {
  const theme = useTheme()
  return (
    <>
      <BackHeader title="Appearance" back="/settings" />
      <section className="screen settings">
        <div className="settings__appearance">
          <Segmented<ThemeChoice> label="Appearance" options={OPTIONS} value={theme} onChange={setTheme} />
          <p className="settings__help">System follows your phone’s light or dark setting. The choice is saved on this device only.</p>
        </div>
      </section>
    </>
  )
}
