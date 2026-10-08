import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router'
import '@fontsource-variable/sora'
import '@fontsource-variable/plus-jakarta-sans'
import '@fontsource-variable/jetbrains-mono'
import './index.css'
import { SessionProvider } from './session/SessionProvider'
import { router } from './router'
import { queryClient } from './queryClient'
import { registerSW } from 'virtual:pwa-register'
import { setupPwaUpdates } from './pwa/update'
import { listenForSwNavigation } from './pwa/swMessages'
import { bootTheme } from './shell/theme'

// Settings › Appearance: data-theme and the status bar colour before React renders, so there is no flash.
bootTheme()

setupPwaUpdates({ register: (opts) => registerSW(opts) })
// A notification tap on an open app window: the worker asks the page to navigate (src/sw.ts).
if ('serviceWorker' in navigator) listenForSwNavigation(navigator.serviceWorker, (path) => void router.navigate(path))

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <RouterProvider router={router} />
      </SessionProvider>
    </QueryClientProvider>
  </StrictMode>,
)
