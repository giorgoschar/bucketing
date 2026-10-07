import { type AmountKey, fromApiAmount, pressKey, toCents } from './amount'
import { amountShares, equalShares, percentShares, toShareList } from './splits'
import type { QrReceipt } from './types'

export type TxnType = 'expense' | 'income'
export type Method = 'card' | 'cash' | 'apple_pay' | 'transfer' | 'other'
export const METHODS: readonly Method[] = ['card', 'cash', 'apple_pay', 'transfer', 'other']
export type TookFrom = 'none' | 'stash' | 'bank'
export type SplitMode = 'equal' | 'amounts' | 'percent'
export type DefaultField = 'bucket' | 'category' | 'payer' | 'method'
export type ReceiptField = 'amount' | 'currency' | 'date' | 'merchant' | 'category'
export interface Share { user_id: string; amount: string }
/** What the defaults store remembers for a context (last entry, a category, a budget). */
export interface Remembered {
  bucket_id?: string | null
  category_id?: string | null
  paid_by?: string | null
  payment_method?: Method
}

export interface ComposerState {
  mode: 'new' | 'edit'
  editId: string | null
  /** Create only; one per composer, reused for every attempt (spec §5.1). */
  clientId: string | null
  type: TxnType
  /** Keypad string, e.g. "4.1". */
  amount: string
  currency: string
  /** Typed rate string; "1" for the household currency, "" when unknown. */
  rate: string
  merchant: string
  bucketId: string | null
  /** Expense linked to a recurring item with no budget: Budget shows "Fixed cost", sent as null. */
  fixedCost: boolean
  categoryId: string | null
  /** "rule: coffee island" when a household rule chose the category. */
  ruleLabel: string | null
  paidBy: string | null
  ownShare: boolean
  method: Method
  tookFrom: TookFrom
  cashMode: boolean
  date: string
  notes: string
  fuelPrice: string
  splitOn: boolean
  splitMode: SplitMode
  /** Every member's share, adding up to the total (split or own share). */
  splits: Share[]
  /** What was typed in the split sheet (amounts or percents by user id): recomputes and reopens the split. */
  splitTyped: Record<string, string>
  countInForecast: boolean
  /** Edit only: the stored value, sent back untouched. */
  excludeFromSettlement: boolean
  receipt: File | null
  storedReceiptPath: string | null
  source: 'manual' | 'qr' | 'photo'
  fromReceipt: ReceiptField[]
  scanCategoryId: string | null
  scanNoTotal: boolean
  rememberRule: boolean
  touched: DefaultField[]
}

export interface BlankInput { type: TxnType; currency: string; date: string; clientId: string | null; meId: string }

export function blankState(p: BlankInput): ComposerState {
  return {
    mode: 'new', editId: null, clientId: p.clientId, type: p.type,
    amount: '', currency: p.currency, rate: '1', merchant: '',
    bucketId: null, fixedCost: false, categoryId: null, ruleLabel: null,
    paidBy: p.meId, ownShare: false, method: p.type === 'income' ? 'transfer' : 'card',
    tookFrom: 'none', cashMode: false, date: p.date, notes: '', fuelPrice: '',
    splitOn: false, splitMode: 'equal', splits: [], splitTyped: {}, countInForecast: true, excludeFromSettlement: false,
    receipt: null, storedReceiptPath: null, source: 'manual', fromReceipt: [], scanCategoryId: null,
    scanNoTotal: false, rememberRule: false, touched: [],
  }
}

export type Action =
  | { type: 'key'; key: AmountKey }
  | { type: 'setType'; value: TxnType; defaults: Remembered }
  | { type: 'setMerchant'; value: string; rule: { pattern: string; category_id: string } | null }
  | { type: 'pickBucket'; id: string | null; remembered: Remembered }
  | { type: 'pickCategory'; id: string | null; remembered: Remembered }
  | { type: 'pickPayer'; id: string }
  | { type: 'setOwnShare'; splits: Share[]; typed?: Record<string, string> }
  | { type: 'pickMethod'; method: Method }
  | { type: 'setTookFrom'; value: TookFrom }
  | { type: 'setCashMode'; on: boolean; meId: string; defaultMethod: Method }
  | { type: 'pickCurrency'; code: string; householdCurrency: string; lastRate: string | undefined }
  | { type: 'setRate'; value: string }
  | { type: 'setDate'; value: string }
  | { type: 'setNotes'; value: string }
  | { type: 'setFuelPrice'; value: string }
  | { type: 'setSplit'; on: boolean; mode: SplitMode; splits: Share[]; typed?: Record<string, string> }
  | { type: 'setForecast'; on: boolean }
  | { type: 'setReceipt'; file: File | null }
  | { type: 'applyScan'; result: QrReceipt; householdCurrency: string; today: string }
  | { type: 'attachPhoto'; file: File }
  | { type: 'setRemember'; on: boolean }
  | { type: 'replace'; state: ComposerState }

const add = <T,>(xs: readonly T[], x: T): T[] => (xs.includes(x) ? [...xs] : [...xs, x])
const drop = <T,>(xs: readonly T[], x: T): T[] => xs.filter((y) => y !== x)

/** Fill the default fields the user has not picked by hand (spec §4.3 "re-defaulting"). */
export function fill(s: ComposerState, r: Remembered, except: DefaultField): ComposerState {
  const free = (f: DefaultField) => f !== except && !s.touched.includes(f)
  const method = free('method') && !s.cashMode && s.type === 'expense' && r.payment_method ? r.payment_method : s.method
  const category = free('category') && r.category_id ? r.category_id : s.categoryId
  return {
    ...s,
    bucketId: free('bucket') && !s.fixedCost && r.bucket_id ? r.bucket_id : s.bucketId,
    categoryId: category,
    ruleLabel: category !== s.categoryId ? null : s.ruleLabel,
    paidBy: free('payer') && !s.cashMode && !s.ownShare && r.paid_by ? r.paid_by : s.paidBy,
    method,
    tookFrom: method === 'cash' ? s.tookFrom : 'none',
  }
}

/**
 * The amount changed: a split follows it. Equal re-equalises; amounts and percent keep what was typed and
 * the payer takes the new remainder. Own share is left alone: validate() flags a mismatch.
 */
export function resplit(s: ComposerState): ComposerState {
  if (s.type !== 'expense' || s.ownShare || !s.splitOn || !s.splits.length) return s
  const ids = s.splits.map((x) => x.user_id)
  const total = toCents(s.amount)
  if (s.splitMode === 'equal') return { ...s, splits: toShareList(ids, equalShares(total, ids, s.paidBy)) }
  if (!s.paidBy || !ids.includes(s.paidBy)) return s // no remainder holder: leave it for validate()
  const shares = s.splitMode === 'amounts'
    ? amountShares(total, ids, s.paidBy, s.splitTyped)
    : percentShares(total, ids, s.paidBy, s.splitTyped)
  return { ...s, splits: toShareList(ids, shares) }
}

export function reduce(s: ComposerState, a: Action): ComposerState {
  const next = step(s, a)
  return next.amount !== s.amount && a.type !== 'replace' ? resplit(next) : next
}

function step(s: ComposerState, a: Action): ComposerState {
  switch (a.type) {
    case 'key':
      return { ...s, amount: pressKey(s.amount, a.key), fromReceipt: drop(s.fromReceipt, 'amount'), scanNoTotal: false }
    case 'setType': {
      if (s.mode === 'edit' || s.type === a.value) return s
      return {
        ...s, type: a.value, touched: [], ownShare: false, splitOn: false, splits: [], splitTyped: {}, cashMode: false,
        tookFrom: 'none', fuelPrice: '', ruleLabel: null,
        bucketId: a.defaults.bucket_id ?? null,
        categoryId: a.defaults.category_id ?? null,
        paidBy: a.defaults.paid_by ?? s.paidBy,
        method: a.defaults.payment_method ?? (a.value === 'income' ? 'transfer' : 'card'),
      }
    }
    case 'setMerchant': {
      const next = { ...s, merchant: a.value.slice(0, 100), fromReceipt: drop(s.fromReceipt, 'merchant') }
      if (a.rule && !s.touched.includes('category')) {
        return { ...next, categoryId: a.rule.category_id, ruleLabel: `rule: ${a.rule.pattern}` }
      }
      return { ...next, ruleLabel: a.rule ? s.ruleLabel : null }
    }
    case 'pickBucket':
      return fill({ ...s, bucketId: a.id, touched: add(s.touched, 'bucket') }, a.remembered, 'bucket')
    case 'pickCategory':
      return fill(
        { ...s, categoryId: a.id, ruleLabel: null, touched: add(s.touched, 'category'), fromReceipt: drop(s.fromReceipt, 'category') },
        a.remembered,
        'category',
      )
    case 'pickPayer':
      return { ...s, paidBy: a.id, ownShare: false, splits: s.ownShare ? [] : s.splits, touched: add(s.touched, 'payer') }
    case 'setOwnShare':
      return { ...s, ownShare: true, paidBy: null, splitOn: false, splits: a.splits, splitTyped: a.typed ?? {}, cashMode: false, tookFrom: 'none', touched: add(s.touched, 'payer') }
    case 'pickMethod':
      return {
        ...s, method: a.method, tookFrom: a.method === 'cash' ? s.tookFrom : 'none',
        cashMode: a.method === 'cash' && s.cashMode, touched: add(s.touched, 'method'),
      }
    case 'setTookFrom':
      return { ...s, tookFrom: a.value }
    case 'setCashMode':
      return a.on
        ? { ...s, cashMode: true, method: 'cash', tookFrom: 'stash', paidBy: a.meId, ownShare: false, splits: s.ownShare ? [] : s.splits }
        : { ...s, cashMode: false, method: a.defaultMethod, tookFrom: 'none' }
    case 'pickCurrency':
      return {
        ...s, currency: a.code, rate: a.code === a.householdCurrency ? '1' : (a.lastRate ?? ''),
        fromReceipt: drop(s.fromReceipt, 'currency'),
      }
    case 'setRate':
      return { ...s, rate: a.value }
    case 'setDate':
      return { ...s, date: a.value, fromReceipt: drop(s.fromReceipt, 'date') }
    case 'setNotes':
      return { ...s, notes: a.value.slice(0, 500) }
    case 'setFuelPrice':
      return { ...s, fuelPrice: a.value }
    case 'setSplit':
      return { ...s, splitOn: a.on, splitMode: a.mode, splits: a.on ? a.splits : [], splitTyped: a.on ? (a.typed ?? {}) : {} }
    case 'setForecast':
      return { ...s, countInForecast: a.on }
    case 'setReceipt':
      return { ...s, receipt: a.file }
    case 'applyScan': {
      const r = a.result
      const from: ReceiptField[] = []
      const next: ComposerState = { ...s, source: 'qr', scanCategoryId: r.category_id, scanNoTotal: r.amount == null, rememberRule: true }
      if (r.amount != null) { next.amount = fromApiAmount(r.amount); from.push('amount') }
      if (r.currency) { next.currency = r.currency; next.rate = r.currency === a.householdCurrency ? '1' : ''; from.push('currency') }
      if (r.date && r.date <= a.today) { next.date = r.date; from.push('date') }
      if (r.merchant) { next.merchant = r.merchant.slice(0, 100); from.push('merchant') }
      if (r.category_id) { next.categoryId = r.category_id; next.ruleLabel = null; from.push('category') }
      return { ...next, fromReceipt: from }
    }
    case 'attachPhoto':
      return { ...s, receipt: a.file, source: 'photo' }
    case 'setRemember':
      return { ...s, rememberRule: a.on }
    case 'replace':
      return a.state
  }
}
