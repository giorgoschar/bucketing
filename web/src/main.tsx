import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router'
import '@fontsource-variable/sora'
import '@fontsource-variable/plus-jakarta-sans'
import '@fontsource-variable/jetbrains-mono'
import './index.css'
import { SessionProvider } from './session/SessionProvider'
import { router } from './router'

const queryClient = new QueryClient({
  defaultOptions: { queries: { networkMode: 'offlineFirst', staleTime: 30_000 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <SessionProvider>
        <RouterProvider router={router} />
      </SessionProvider>
    </QueryClientProvider>
  </StrictMode>,
)
