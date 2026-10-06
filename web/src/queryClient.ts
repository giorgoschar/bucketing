import { QueryClient } from '@tanstack/react-query'

/** The app's one query cache; the session clears it on every sign-out so no data outlives a user. */
export const queryClient = new QueryClient({
  defaultOptions: { queries: { networkMode: 'offlineFirst', staleTime: 30_000 } },
})
