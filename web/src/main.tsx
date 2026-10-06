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

setupPwaUpdates({ register: (opts) => registerSW(opts) })

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <RouterProvider router={router} />
      </SessionProvider>
    </QueryClientProvider>
  </StrictMode>,
)
