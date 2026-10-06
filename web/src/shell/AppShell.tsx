import { Outlet } from 'react-router'
import { useSession } from '../session/SessionProvider'
import { SignIn } from '../session/SignIn'
import { TabBar } from './TabBar'
import './shell.css'

export function AppShell() {
  const { status } = useSession()
  if (status === 'loading') return <div className="boot" aria-busy="true" />
  if (status === 'signedOut') return <SignIn />
  return (
    <div className="shell">
      <main className="shell__main"><Outlet /></main>
      <TabBar />
    </div>
  )
}
