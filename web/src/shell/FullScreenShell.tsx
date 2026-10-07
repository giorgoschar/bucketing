import { useEffect } from 'react'
import { Outlet } from 'react-router'
import { clearPending } from '../data/pending'
import { installQueueBridge } from '../data/queueBridge'
import { startReplayTriggers } from '../offline/queue'
import { queryClient } from '../queryClient'
import { useSession } from '../session/SessionProvider'
import { SignIn } from '../session/SignIn'
import { Toaster } from '../ui/Toast'
import './shell.css'

/**
 * Layout for full-screen flows (the composer): the same sign-in gate, queue bridge and offline replay
 * as AppShell, without the tab bar. Auth-callback banners stay AppShell's job (callbacks land on /).
 */
export function FullScreenShell() {
  const { status } = useSession()
  useEffect(() => {
    if (status !== 'signedIn') return
    const stopBridge = installQueueBridge(queryClient)
    const stopReplay = startReplayTriggers()
    return () => {
      stopReplay()
      stopBridge()
      clearPending() // as AppShell: this account's markers must not outlive it
    }
  }, [status])
  if (status === 'loading') return <div className="boot" aria-busy="true" />
  if (status === 'signedOut') return <SignIn result={{ error: null, linked: false }} />
  return (
    <>
      <Outlet />
      <Toaster />
    </>
  )
}
