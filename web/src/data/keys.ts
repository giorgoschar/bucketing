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
    /** TxnPage: one page of the Activity feed for a filter */
    list: (filter: object, page: number) => ['transactions', 'list', filter, page] as const,
    /** HistoryEvent[]: GET /transactions/{id}/history */
    history: (id: string) => ['transactions', 'history', id] as const,
    /** Counts: GET /transactions/counts (the chip badges) */
    counts: () => ['transactions', 'counts'] as const,
  },
  /** DuplicateGroup[]: GET /transactions/duplicates */
  duplicates: () => ['duplicates'] as const,
  /** RecentBatch[]: GET /transactions/bulk?limit=10 */
  bulkRecent: () => ['bulk-recent'] as const,
  household: () => ['household'] as const,
  buckets: () => ['buckets'] as const,
  categories: () => ['categories'] as const,
  /** The raw GET /buckets rows. keys.buckets() holds the narrowed Bucket[] (no show_income or icon), which the
   *  bucket pickers need. It sits under the 'buckets' prefix, so invalidating keys.buckets() covers it too. */
  bucketsFull: () => ['buckets', 'full'] as const,
  categoryRules: () => ['category-rules'] as const,
  cashStash: () => ['cash-stash'] as const,
  /** The prefix of every Plan › Cash read below (one invalidation covers them). cashStash is separate. */
  cashAll: () => ['cash'] as const,
  /** CashWalletsOut: GET /cash/wallets?month=YYYY-MM (Plan › Cash, Home's cash row) */
  cashWallets: (month: string) => ['cash', 'wallets', month] as const,
  /** CashMovementsOut: GET /cash/movements?month=YYYY-MM */
  cashMovements: (month: string) => ['cash', 'movements', month] as const,
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

// ---- 2d: Insights and Settings ------------------------------------------------------------
// Call sites pass the household id; 2d-only keys carry it, keys shared with 2a ignore it
// (2a scopes the device cache by household) so both phases hit one cache entry.
export const insightsKeys = {
  all: (_hh: string) => keys.insights.all,
  overview: (hh: string, period: string, lens: string, filters: string) => ['insights', 'overview', hh, period, lens, filters] as const,
  person: (hh: string, period: string, userId: string) => ['insights', 'person', hh, period, userId] as const,
  category: (hh: string, id: string, period: string, lens: string) => ['insights', 'category', hh, id, period, lens] as const,
  vsUsual: (_hh: string, month: string) => keys.insights.categoriesVsUsual(month),
  planMonth: (_hh: string, month: string) => keys.plan.month(month),
}

export const settingsKeys = {
  profile: (hh: string) => ['settings', 'profile', hh] as const,
  security: (hh: string) => ['settings', 'security', hh] as const,
  tokens: (hh: string) => ['settings', 'tokens', hh] as const,
  notifications: (hh: string) => ['settings', 'notifications', hh] as const,
  household: (_hh: string) => keys.household(),
  categories: (_hh: string) => keys.categories(),
  rules: (_hh: string) => keys.categoryRules(),
  buckets: (_hh: string) => keys.buckets(),
}
