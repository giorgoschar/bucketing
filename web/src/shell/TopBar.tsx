import { useRef, type ReactNode } from 'react'
import { useInRouterContext, useLocation, useNavigate } from 'react-router'
import { SEARCH_STATE } from '../features/search/searchState'
import { SearchIcon } from './icons'
import { AccountDialog, type AccountDialogHandle, MyAvatar } from './AccountDialog'

/** The four tab screens: the phone's search icon shows on these only (Phase C spec §4.2). */
const SEARCHABLE = new Set(['/', '/activity', '/plan', '/insights'])

function SearchButton() {
  const { pathname, search, hash, state } = useLocation()
  const navigate = useNavigate()
  if (!SEARCHABLE.has(pathname)) return null
  // A pushed history entry: Back removes the flag and so closes the search.
  const open = () => { void navigate({ pathname, search, hash }, { state: { ...(typeof state === 'object' ? state : null), [SEARCH_STATE]: true } }) }
  return (
    <button type="button" className="topbar__search" aria-label="Search" onClick={open}><SearchIcon /></button>
  )
}

/** `actions` (icon buttons for the screen) render before the account button. */
export function TopBar({ title, actions }: { title: string; actions?: ReactNode }) {
  const account = useRef<AccountDialogHandle>(null)
  const inRouter = useInRouterContext()
  return (
    <header className="topbar">
      <h1 className="topbar__title">{title}</h1>
      <div className="topbar__end">
        {actions}
        {inRouter && <SearchButton />}
        <button
          type="button"
          className="topbar__account"
          aria-label="Account"
          aria-haspopup="dialog"
          onClick={() => account.current?.open()}
        >
          <MyAvatar />
        </button>
      </div>
      <AccountDialog ref={account} />
    </header>
  )
}
