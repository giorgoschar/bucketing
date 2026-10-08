import { QueryClient } from '@tanstack/react-query'
import { isRetryable } from './data/http'

/** The app's one query cache; the session clears it on every sign-out so no data outlives a user. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      networkMode: 'offlineFirst',
      staleTime: 30_000,
      // Two retries for network errors and 5xx; a 4xx (401 above all) fails at once.
      retry: (count, err) => count < 2 && isRetryable(err),
    },
  },
})
