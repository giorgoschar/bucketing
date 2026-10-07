import type {
  Bucket, BudgetRowOut, Category, CategoryUsualOut, EntryOut, Household, MatchOut, Member, MonthPictureOut,
  PaceOut, RecurringItemOut, TransactionRow, UpcomingDayOut, YearMonthOut, YearOut,
} from '../data/types'
import type { components } from '../api/schema'
import type { Routes } from './fakeApi'
import type { CashMovementOut, CashWalletMemberOut, CashWalletsOut, WalletOut } from '../features/plan/cash/types'

/** Cosmote, out, €38.90, due Fri 9 Oct 2026, expected. */
export function entry(over: Partial<EntryOut> = {}): EntryOut {
  return {
    id: 'e1', item_id: 'i1', name: 'Cosmote', direction: 'out', due_date: '2026-10-09', status: 'expected',
    amount: 38.9, estimated: false, currency: 'EUR', bucket_id: null, category_id: null, transaction_id: null,
    overdue: false, infrequent: false, payment_method: 'card', ...over,
  }
}

export function day(date: string, entries: EntryOut[], net_this_month: number): UpcomingDayOut {
  return { date, entries, net_this_month }
}

export function item(over: Partial<RecurringItemOut> = {}): RecurringItemOut {
  return {
    id: 'i1', name: 'Cosmote', direction: 'out', amount: 38.9, currency: 'EUR', category_id: null, bucket_id: null,
    rule_kind: 'monthly_day', interval_months: 1, rule_day: 9, rule_month: null, rule_adjust: 'none', rule_days: null,
    rule_weekday: null, rule_interval_weeks: null, start_date: '2026-01-09', end_date: null, total_occurrences: null,
    contract_end_date: null, paid_by_default: 'u1', payer_mode: 'single', is_auto_pay: false, is_active: true,
    notes: null, splits: [], next_entry: entry(), has_history: false, payment_method: 'card', ...over,
  }
}

/** October 2026: in 3,150 so far, net projected +2,311.10. */
export function monthPicture(over: Partial<MonthPictureOut> = {}): MonthPictureOut {
  return {
    month: '2026-10',
    income: { so_far: 3150, still_to_come: 1500, projected: 4650 },
    fixed: { so_far: 600, still_to_come: 238.9, projected: 838.9 },
    buckets: {
      so_far: 685, still_to_come: 815, projected: 1500,
      rows: [
        { bucket_id: 'b1', name: 'Day to day', budget: 1200, so_far: 685, still_to_come: 515, projected: 1200 },
        { bucket_id: 'b2', name: 'Kids', budget: null, so_far: 0, still_to_come: 300, projected: 300 },
      ],
    },
    net_projected: 2311.1, events_spent: 410, cash: 45, estimated: false, ...over,
  }
}

export function yearMonth(month: string, income: number, out: number, estimated = false): YearMonthOut {
  return { month, income, out, estimated }
}
export function yearOut(months: YearMonthOut[], over: Partial<YearOut> = {}): YearOut {
  return { months, infrequent_monthly_average: 42.5, estimated: false, ...over }
}

export function budgetRow(over: Partial<BudgetRowOut> = {}): BudgetRowOut {
  return {
    bucket_id: 'b1', name: 'Day to day', kind: 'monthly', budget: 1200, spent: 904, pct: 75.3,
    period_start: '2026-10-01', period_end: '2026-10-31', days_left: null, archive_suggested: false, ...over,
  }
}
export function pace(over: Partial<PaceOut> = {}): PaceOut {
  return { bucket_id: 'b1', name: 'Day to day', budget: 1200, spent: 904, pct: 75.3, pace: 1310, over_pace: true, ...over }
}

export function match(over: Partial<MatchOut> = {}): MatchOut {
  return {
    id: 'm1', label: 'Cosmote', transaction_id: 't1', transaction_date: '2026-10-03', transaction_amount: 38.9,
    merchant: 'Cosmote', notes: null, entry: entry({ due_date: '2026-10-05' }), ...over,
  }
}

export function categoryUsual(over: Partial<CategoryUsualOut> = {}): CategoryUsualOut {
  return { category_id: 'c1', name: 'Groceries', icon: '🛒', color: '#f59e0b', this_month: 412, usual: 300, flagged: true, ...over }
}

export function member(over: Partial<Member> = {}): Member {
  return { user_id: 'u1', role: 'owner', display_name: 'Giorgos', username: 'giorgos', avatar_color: null, ...over }
}
export function household(
  members: Member[] = [member(), member({ user_id: 'u2', role: 'member', display_name: 'Maria', username: 'maria' })],
): Household {
  return { id: 'h1', name: 'Home', default_currency: 'EUR', members }
}

export function txn(over: Partial<TransactionRow> = {}): TransactionRow {
  return {
    id: 't1', type: 'expense', amount: 64.2, currency: 'EUR', transaction_date: '2026-10-06', merchant: 'Sklavenitis',
    notes: null, bucket_id: 'b1', category_id: null, paid_by: 'u1', payment_method: 'card', recurring_bill_id: null, ...over,
  }
}
// GET /transactions is the typed Activity feed since 2c-B2: each row is the full
// TransactionOut and the page carries day_totals. The 2a reader ignores the extras.
export function page(items: TransactionRow[]): components['schemas']['TransactionPage'] {
  return {
    total: items.length, page: 1, page_size: 10, day_totals: {},
    items: items.map((r) => ({
      household_id: 'h1', exchange_rate: 1, payer_mode: 'single', receipt_path: null, fuel_price_per_litre: null,
      fuel_litres: null, exclude_from_forecast: false, exclude_from_settlement: false, created_at: null,
      splits: [], has_take: false, missing_payer: false, ...r, payment_method: r.payment_method ?? 'card',
    })),
  }
}

export function bucket(over: Partial<Bucket> = {}): Bucket {
  return { id: 'b1', name: 'Day to day', kind: 'monthly', status: 'active', budget: 1200, start_date: null, end_date: null, show_income: false, ...over }
}
export function category(over: Partial<Category> = {}): Category {
  return { id: 'c1', name: 'Groceries', icon: '🛒', color: '#f59e0b', system_key: null, is_default: false, locked: false, expense_count: 0, rule_count: 0, ...over }
}

/** Handlers for the shared reads in data/reads.ts (household, items, buckets, categories). */
export function readRoutes(): Routes {
  return {
    'GET /api/v1/settings/household': () => household(),
    'GET /api/v1/recurring': () => [item()],
    'GET /api/v1/buckets': () => [bucket()],
    'GET /api/v1/settings/categories': () => [category()],
  }
}

// ---- Plan › Cash (cash spec §3.2/§3.3). /cash/wallets is not in the generated schema until the
// integration step, so these routes are cast to Routes (fakeApi matches them at runtime all the same).

/** Giorgos (u1, the viewer) took €120 and logged €75: €45 not yet logged. */
export function wallet(over: Partial<WalletOut> = {}): WalletOut {
  return {
    carried: 0, taken: 120, put_back: 0, still_have: null, spent: 120, logged: 75, outs: 0, not_yet_logged: 45, ...over,
  }
}
export function walletMember(over: Partial<CashWalletMemberOut> = {}): CashWalletMemberOut {
  return { member_id: 'u1', name: 'Giorgos', is_me: true, wallet: wallet(), ...over }
}
/** October 2026: stash €380; Giorgos €45 not logged, Maria all logged. */
export function cashWallets(over: Partial<CashWalletsOut> = {}): CashWalletsOut {
  return {
    month: '2026-10',
    stash: 380,
    members: [
      walletMember(),
      walletMember({
        member_id: 'u2', name: 'Maria', is_me: false,
        wallet: wallet({ taken: 60, put_back: null, spent: 60, logged: 60, not_yet_logged: 0 }),
      }),
    ],
    ...over,
  }
}
export function cashMovement(over: Partial<CashMovementOut> = {}): CashMovementOut {
  return {
    id: 'm1', user_id: 'u1', kind: 'take', stash_owner_id: null, amount: 40, currency: 'EUR', category_id: null,
    note: null, movement_date: '2026-10-04', transaction_id: null, created_at: '2026-10-04T10:00:00', deleted: false, ...over,
  }
}
export function cashRoutes(
  o: { wallets?: CashWalletsOut; movements?: CashMovementOut[] } = {},
): Routes {
  const wallets = o.wallets ?? cashWallets()
  return {
    'GET /api/v1/cash/wallets': () => wallets,
    'GET /api/v1/cash/movements': () => ({ items: o.movements ?? [], stash: wallets.stash }),
    'POST /api/v1/cash/movements': () => Response.json(cashMovement({ id: 'new' }), { status: 201 }),
    'DELETE /api/v1/cash/movements/{movement_id}': () => null,
  } as unknown as Routes
}
