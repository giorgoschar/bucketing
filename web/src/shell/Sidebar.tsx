import { useEffect, useRef } from 'react'
import { NavLink } from 'react-router'
import { AccountDialog, type AccountDialogHandle, MyAvatar } from './AccountDialog'
import { useOpenAdd } from './addPanel'
import { CalendarRangeIcon, ChartPieIcon, HouseIcon, ListIcon, PlusIcon, SettingsIcon } from './icons'

const link = ({ isActive }: { isActive: boolean }) => (isActive ? 'sidebar__link is-active' : 'sidebar__link')

const TYPING = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])'
const OPEN_DIALOG = 'dialog[open], [role="dialog"], [aria-modal="true"]'

/** Desktop navigation (Phase A spec §4.2): the tab bar's destinations, Add, Settings and the account. */
export function Sidebar() {
  const openAdd = useOpenAdd()
  const account = useRef<AccountDialogHandle>(null)
  const openRef = useRef(openAdd)
  useEffect(() => { openRef.current = openAdd })

  // N opens Add, unless a field has focus, a dialog is open, or it is part of a shortcut.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() !== 'n' || e.metaKey || e.ctrlKey || e.altKey || e.repeat || e.defaultPrevented) return
      const t = e.target as Element | null
      if (t?.closest?.(TYPING) || document.activeElement?.closest?.(TYPING)) return
      if (document.querySelector(OPEN_DIALOG)) return
      e.preventDefault()
      openRef.current()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <nav className="sidebar" aria-label="Main">
      <p className="sidebar__brand">Tameio</p>
      <button type="button" className="btn btn--primary sidebar__add" aria-label="Add" aria-keyshortcuts="N" onClick={openAdd}>
        <PlusIcon />
        <span aria-hidden="true">Add</span>
        <kbd className="sidebar__key" aria-hidden="true">N</kbd>
      </button>
      <div className="sidebar__links">
        <NavLink to="/" end className={link}><HouseIcon />Home</NavLink>
        <NavLink to="/activity" className={link}><ListIcon />Activity</NavLink>
        <NavLink to="/plan" className={link}><CalendarRangeIcon />Plan</NavLink>
        <NavLink to="/insights" className={link}><ChartPieIcon />Insights</NavLink>
      </div>
      <div className="sidebar__foot">
        <NavLink to="/settings" className={link}><SettingsIcon />Settings</NavLink>
        <button type="button" className="sidebar__account" aria-label="Account" aria-haspopup="dialog"
          onClick={() => account.current?.open()}>
          <MyAvatar />
        </button>
      </div>
      <AccountDialog ref={account} />
    </nav>
  )
}
