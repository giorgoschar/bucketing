import type { QueryKey } from '@tanstack/react-query'

/**
 * Every query key in the app. The plain prefixes (keys.plan.all, ...) are what invalidation and optimistic
 * patches match on. The household id is not in these keys: it is in the device-cache key (cacheKeyFor).
 */
export const keys = {
  plan: {
    all: ['plan'] as const,
    /** UpcomingDayOut[] */
    upcoming: (days: number) => ['plan', 'upcoming', days] as const,
    /** MonthPictureOut; month is 'YYYY-MM' */
    month: (month: string) => ['plan', 'month', month] as const,
    year: () => ['plan', 'year'] as const,
    budgets: () => ['plan', 'budgets'] as const,
    pace: () => ['plan', 'pace'] as const,
  },
  insights: {
    all: ['insights'] as const,
    /** CategoryUsualOut[] */
    categoriesVsUsual: (month: string) => ['insights', 'categories-vs-usual', month] as const,
  },
  recurring: {
    all: ['recurring'] as const,
    /** RecurringItemOut[] */
    list: () => ['recurring', 'list'] as const,
    one: (id: string) => ['recurring', 'one', id] as const,
    entries: (from: string, to: string) => ['recurring', 'entries', from, to] as const,
  },
  home: {
    all: ['home'] as const,
    /** EntryOut[]: GET /recurring/entries for the overdue window (spec §5.2) */
    overdue: (from: string, to: string) => ['home', 'overdue', from, to] as const,
  },
  /** MatchOut[] */
  matches: () => ['matches'] as const,
  transactions: {
    all: ['transactions'] as const,
    /** TransactionRow[]: the last 10, newest first (Home › Recent; 2b adds pending rows to it) */
    recent: () => ['transactions', 'recent'] as const,
    one: (id: string) => ['transactions', 'one', id] as const,
    /** number: how many transactions an item has (its "history"), from GET /transactions?recurring_bill_id */
    forItem: (itemId: string) => ['transactions', 'item', itemId] as const,
  },
  household: () => ['household'] as const,
  buckets: () => ['buckets'] as const,
  categories: () => ['categories'] as const,
  categoryRules: () => ['category-rules'] as const,
  cashStash: () => ['cash-stash'] as const,
}

/** What each kind of change makes stale (useAction `invalidates`; the queue bridge uses `sync`). */
export const affects = {
  entry: [keys.plan.all, keys.home.all, keys.recurring.all, keys.matches(), keys.transactions.all, keys.insights.all],
  item: [keys.plan.all, keys.home.all, keys.recurring.all],
  sync: [
    keys.plan.all, keys.home.all, keys.recurring.all, keys.matches(), keys.transactions.all, keys.insights.all,
    keys.buckets(),
  ],
} satisfies Record<string, readonly QueryKey[]>
