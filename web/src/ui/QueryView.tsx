import type { ReactNode } from 'react'
import { EmptyState } from './EmptyState'
import { OfflineBanner } from './OfflineBanner'

/** The parts of a cached query (data/cachedQuery) that decide what a screen shows. */
export interface QueryViewState<T> {
  data: T | undefined
  dataUpdatedAt: number
  isLoading: boolean
  offline: boolean
  stale: boolean
  noData: boolean
  refetch: () => void
}

export interface QueryViewProps<T> {
  result: QueryViewState<T>
  /** Spec §8: "No saved data yet. Connect once to load Plan." */
  noDataText: string
  /** false for a secondary query on a screen that already shows the banner once. */
  showBanner?: boolean
  loadingLabel?: string
  children: (data: T) => ReactNode
}

export function QueryView<T>({ result, noDataText, showBanner = true, loadingLabel = 'Loading', children }: QueryViewProps<T>) {
  if (result.data !== undefined) {
    return (
      <>
        {showBanner && result.stale && <OfflineBanner updatedAt={result.dataUpdatedAt} />}
        {children(result.data)}
      </>
    )
  }
  if (result.noData) {
    return result.offline ? (
      <EmptyState title={noDataText} />
    ) : (
      <EmptyState title="Couldn’t load this." action={{ label: 'Try again', onClick: result.refetch }} />
    )
  }
  return <div className="ui-skeleton" role="status" aria-busy="true" aria-label={loadingLabel} />
}
