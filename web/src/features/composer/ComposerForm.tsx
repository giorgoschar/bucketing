import { useEffect, useReducer, useRef, useState } from 'react'
import { useBlocker, useNavigate } from 'react-router'
import { CloseIcon } from '../../shell/icons'
import { AmountDisplay } from '../../ui/AmountDisplay'
import { Keypad } from '../../ui/Keypad'
import { Pill } from '../../ui/Pill'
import { type AmountKey, centsToString, convertCents, displayAmount, parseRate, toApiAmount, toCents } from './amount'
import { Segmented, type ToastInput, useComposerToast, useOnline } from './bridge'
import { CashControls } from './CashControls'
import { ConfirmSheet } from './ConfirmSheet'
import { currencyName, currencySymbol, formatCents, spokenMoney } from './currencies'
import { dayLabel, todayLocal } from './dates'
import { type DefaultsRecord, matchRule, sanitize, suggestMerchants } from './defaults'
import { DuplicateCard } from './DuplicateCard'
import type { ComposerData } from './hooks/useComposerData'
import { useDuplicateCheck } from './hooks/useDuplicateCheck'
import { useReceiptUpload } from './hooks/useReceiptUpload'
import { useSaveTransaction } from './hooks/useSaveTransaction'
import { useUndoCreate } from './hooks/undo'
import { firstProblem, isDirtyNew, moreDirty, toUpdateBody, validate } from './model'
import { MoreSheet } from './MoreSheet'
import { BucketSheet } from './pickers/BucketSheet'
import { CategorySheet } from './pickers/CategorySheet'
import { CurrencySheet } from './pickers/CurrencySheet'
import { DateSheet } from './pickers/DateSheet'
import { MethodSheet } from './pickers/MethodSheet'
import { PayerSheet } from './pickers/PayerSheet'
import { METHOD_LABELS, memberName } from './pickers/labels'
import { type ComposerState, reduce, type Remembered, type TxnType } from './state'
import type { Duplicate } from './types'
import { useClose } from './useClose'

type SheetName = 'bucket' | 'category' | 'payer' | 'method' | 'currency' | 'date' | 'more'

const QUEUED = "Saved on this phone. It will sync when you're back online."
const QUEUED_NO_RECEIPT = "Saved on this phone. The receipt wasn't attached: add it when you're back online."
const UPLOAD_FAILED = "Saved. The receipt didn't upload."
const UNDO_MS = 5000

export function ComposerForm({ initial, data, defaults }: { initial: ComposerState; data: ComposerData; defaults: DefaultsRecord }) {
  const [s, dispatch] = useReducer(reduce, initial)
  const today = todayLocal()
  const online = useOnline()
  const navigate = useNavigate()
  const close = useClose()
  const toast = useComposerToast()
  const ctx = { hh: data.hh, householdCurrency: data.householdCurrency, fuelCategoryId: data.fuelCategoryId, meId: data.meId }
  const save = useSaveTransaction(s, ctx, defaults)
  const checkDuplicate = useDuplicateCheck()
  const upload = useReceiptUpload()
  const undo = useUndoCreate()
  const [sheet, setSheet] = useState<SheetName | null>(null)
  const [dup, setDup] = useState<Duplicate | null>(null)
  const [typing, setTyping] = useState(false)
  const [stashCents, setStashCents] = useState<number | null>(null)
  const v = validate(s, { ...ctx, today, stashCents })

  const memberIds = data.members.map((m) => m.user_id)
  const lookup = (type: TxnType = s.type) => ({ buckets: data.buckets, categories: data.categories, memberIds, type })
  const remembered = (r: Remembered | undefined) => sanitize(r, lookup())

  // Closing (spec §3): a dirty draft asks first; a save or "Open that one" leaves without asking.
  const [initialBody] = useState(() => (initial.mode === 'edit' ? JSON.stringify(toUpdateBody(initial, ctx)) : ''))
  const dirty = s.mode === 'new' ? isDirtyNew(s) : JSON.stringify(toUpdateBody(s, ctx)) !== initialBody
  const leaving = useRef(false)
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => dirty && !leaving.current && currentLocation.pathname !== nextLocation.pathname,
  )
  const leave = (to?: string) => {
    leaving.current = true
    if (to) void navigate(to, { replace: true })
    else close()
  }

  const cents = toCents(s.amount)
  const money = formatCents(cents, s.currency)
  const bucketName = data.buckets.find((b) => b.id === s.bucketId)?.name

  function savedToast(id: string): ToastInput {
    if (s.mode === 'edit') return { text: 'Saved changes' }
    const text = s.type === 'income'
      ? `Saved income ${money}${bucketName ? ` to ${bucketName}` : ''}`
      : `Saved ${money} to ${s.fixedCost ? 'Fixed cost' : bucketName}`
    return { text, durationMs: UNDO_MS, action: { label: 'Undo', onPress: () => void undo(id) } }
  }

  async function uploadReceipt(id: string, file: File) {
    if ((await upload(id, file)) === 'ok') return
    toast({ text: UPLOAD_FAILED, action: { label: 'Retry', onPress: () => void uploadReceipt(id, file) } })
  }

  const submitting = useRef(false)
  async function onSave(skipDuplicate = false) {
    if (!v.ok || submitting.current) return
    submitting.current = true
    try {
      if (s.mode === 'new' && s.type === 'expense' && !skipDuplicate && online) {
        const found = await checkDuplicate({ amount: toApiAmount(s.amount), transaction_date: s.date, bucket_id: s.bucketId })
        if (found.length) {
          setDup(found[0])
          return
        }
      }
      setDup(null)
      const r = s.mode === 'new' ? await save.saveNew() : await save.saveEdit()
      if (r.status === 'busy' || r.status === 'failed') return // useAction already showed the server's detail
      const receipt = s.receipt
      leave()
      if (r.status === 'queued') {
        toast({ text: receipt ? QUEUED_NO_RECEIPT : QUEUED })
        return
      }
      toast(savedToast(r.id))
      if (receipt) void uploadReceipt(r.id, receipt)
    } finally {
      submitting.current = false
    }
  }

  // Hardware keyboard (spec §4.2): digits, "." or ",", Backspace, Enter saves. Not while a field or sheet has focus.
  const onSaveRef = useRef(onSave)
  useEffect(() => { onSaveRef.current = onSave })
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (sheet || dup || blocker.state === 'blocked') return
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      let key: AmountKey | null = null
      if (/^[0-9]$/.test(e.key)) key = e.key as AmountKey
      else if (e.key === '.' || e.key === ',') key = '.'
      else if (e.key === 'Backspace') key = 'back'
      if (key) dispatch({ type: 'key', key })
      else if (e.key === 'Enter') void onSaveRef.current()
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [sheet, dup, blocker.state])

  const switchType = (value: TxnType) => {
    const r = sanitize(value === 'income' ? defaults.lastIncome : defaults.last, lookup(value))
    dispatch({ type: 'setType', value, defaults: { ...r, paid_by: r.paid_by ?? data.meId } })
  }
  const toggleCash = () =>
    dispatch({ type: 'setCashMode', on: !s.cashMode, meId: data.meId, defaultMethod: remembered(defaults.last).payment_method ?? 'card' })

  const rule = matchRule(s.merchant, data.rules)
  const suggestions = typing ? suggestMerchants(s.merchant, data.merchants) : []
  const rate = parseRate(s.rate)
  const converted = s.currency !== data.householdCurrency && rate !== null
    ? `≈ ${formatCents(convertCents(cents, rate), data.householdCurrency)}`
    : null
  const hint = firstProblem(v.problems)
  const payer = data.members.find((m) => m.user_id === s.paidBy)
  const category = data.categories.find((c) => c.id === s.categoryId)
  const income = s.type === 'income'
  const saveLabel = s.mode === 'edit' ? 'Save changes' : income ? `Save income ${money}` : `Save ${money}`
  const saveName = s.mode === 'edit'
    ? 'Save changes'
    : income
      ? `Save income ${spokenMoney(cents, s.currency)}`
      : `Save ${spokenMoney(cents, s.currency)}${bucketName ? ` to ${bucketName}` : ''}`
  const allowOwnShare = false // C4-3 enables "Each paid own share" together with the split sheet

  const pillIcon = (glyph: string) => <span className="ck-pill__glyph">{glyph}</span>
  const budgetPill = s.fixedCost
    ? <Pill label="Budget" value="Fixed cost" readOnly />
    : <Pill label="Budget" value={bucketName ?? (income ? 'None' : 'Choose a budget')} empty={!s.bucketId && !income}
        onPress={() => setSheet('bucket')} />
  const categoryPill = (
    <Pill label="Category" value={category?.name ?? 'None'} empty={!category && income}
      icon={category ? pillIcon(category.icon || category.name.slice(0, 1).toUpperCase()) : undefined}
      tag={s.ruleLabel ?? (s.fromReceipt.includes('category') ? 'from receipt' : null)}
      onPress={() => setSheet('category')} />
  )
  const payerValue = s.ownShare ? 'Each paid own share' : s.cashMode ? 'You' : memberName(payer)

  return (
    <div className="composer" data-type={s.type}>
      <header className="composer__bar">
        <button type="button" className="ui-iconbtn composer__close" aria-label="Close" onClick={close}>
          <CloseIcon />
        </button>
        <Segmented label="Entry type" value={s.type} onChange={switchType} disabled={s.mode === 'edit'}
          options={[{ value: 'expense', label: 'Expense' }, { value: 'income', label: 'Income' }]} />
        <span className="composer__slot">{!online && <span className="composer__offline">Offline</span>}</span>
      </header>

      <div className="composer__body">
        {s.mode === 'new' && !income && (
          <div className="composer__modes" role="group" aria-label="Entry mode">
            <button type="button" className={s.cashMode ? 'ck-chip on' : 'ck-chip'} aria-pressed={s.cashMode} onClick={toggleCash}>
              Cash from wallet
            </button>
          </div>
        )}

        <AmountDisplay text={displayAmount(s.amount)} symbol={currencySymbol(s.currency)} currency={s.currency}
          spoken={`Amount ${centsToString(cents)} ${currencyName(s.currency)}`} tone={income ? 'income' : 'default'}
          converted={converted} onCurrency={() => setSheet('currency')}
          tag={s.fromReceipt.includes('amount') ? 'from receipt' : null} />
        {s.scanNoTotal && <p className="composer__hint">Couldn't find the total</p>}

        <div className="composer__merchant-wrap">
          <input className="composer__merchant" aria-label="Merchant" placeholder="Where? (optional)" maxLength={100}
            autoComplete="off" autoCorrect="off" enterKeyHint="done" value={s.merchant}
            onChange={(e) => dispatch({ type: 'setMerchant', value: e.target.value, rule: matchRule(e.target.value, data.rules) })}
            onFocus={() => setTyping(true)} onBlur={() => setTyping(false)}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
          {suggestions.length > 0 && (
            <ul className="composer__suggest" role="listbox" aria-label="Recent places">
              {suggestions.map((m) => (
                <li key={m} role="option" aria-selected={false} className="composer__suggest-item"
                  // mousedown keeps the input focused so the pick lands before blur hides the list.
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => dispatch({ type: 'setMerchant', value: m, rule: matchRule(m, data.rules) })}>
                  {m}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="pills composer__pills">
          {income ? (
            <>
              <Pill label="Received by" value={memberName(payer)} onPress={() => setSheet('payer')} />
              {categoryPill}
              {budgetPill}
              <Pill label="Date" value={dayLabel(s.date, today)} onPress={() => setSheet('date')} />
            </>
          ) : (
            <>
              {budgetPill}
              {categoryPill}
              <Pill label="Payer" value={payerValue} readOnly={s.cashMode} onPress={() => setSheet('payer')} />
              <Pill label="Method" value={METHOD_LABELS[s.method]} onPress={() => setSheet('method')} />
            </>
          )}
        </div>

        {s.mode === 'new' && !income && s.method === 'cash' && (
          <CashControls s={s} dispatch={dispatch} householdCurrency={data.householdCurrency} onStash={setStashCents} />
        )}

        {dup && <DuplicateCard dup={dup} onOpen={() => leave(`/edit/${dup.id}`)} onSaveAnyway={() => void onSave(true)} />}

        <button type="button" className="composer__more" onClick={() => setSheet('more')}
          aria-label={moreDirty(s, { ...ctx, today }) ? 'More options, changed' : 'More options'}>
          {income ? 'More: notes, receipt' : 'More: date, split, notes, receipt'}
          {moreDirty(s, { ...ctx, today }) && <span className="composer__dot" aria-hidden="true" />}
        </button>
      </div>

      <div className="composer__foot">
        {hint && <p className="composer__problem">{hint}</p>}
        <Keypad onKey={(k) => dispatch({ type: 'key', key: k })} hidden={typing} />
        <button type="button" aria-label={saveName} disabled={!v.ok || save.saving} onClick={() => void onSave()}
          className={`btn btn--primary btn--lg btn--block composer__save${income ? ' composer__save--income' : ''}`}>
          {saveLabel}
        </button>
      </div>

      {!s.fixedCost && (
        <BucketSheet open={sheet === 'bucket'} onClose={() => setSheet(null)} buckets={data.buckets} type={s.type}
          selectedId={s.bucketId}
          onPick={(id) => dispatch({ type: 'pickBucket', id, remembered: id ? remembered(defaults.byBucket[id]) : {} })} />
      )}
      <CategorySheet open={sheet === 'category'} onClose={() => setSheet(null)} categories={data.categories}
        recentIds={defaults.recentCategoryIds} selectedId={s.categoryId}
        suggestion={rule ? { id: rule.category_id, reason: `rule: ${rule.pattern}` } : null}
        onPick={(id) => dispatch({ type: 'pickCategory', id, remembered: remembered(defaults.byCategory[id]) })} />
      {!s.cashMode && (
        <PayerSheet open={sheet === 'payer'} onClose={() => setSheet(null)} title={income ? 'Received by' : 'Payer'}
          members={data.members} selectedId={s.paidBy} ownShare={s.ownShare} allowOwnShare={allowOwnShare}
          onPick={(id) => dispatch({ type: 'pickPayer', id })} onOwnShare={() => setSheet(null)} />
      )}
      <MethodSheet open={sheet === 'method'} onClose={() => setSheet(null)} selected={s.method}
        onPick={(m) => dispatch({ type: 'pickMethod', method: m })} />
      <CurrencySheet open={sheet === 'currency'} onClose={() => setSheet(null)} selected={s.currency}
        onPick={(code) => dispatch({ type: 'pickCurrency', code, householdCurrency: data.householdCurrency, lastRate: defaults.rates[code] })} />
      <DateSheet open={sheet === 'date'} onClose={() => setSheet(null)} value={s.date} today={today}
        onPick={(d) => dispatch({ type: 'setDate', value: d })} />
      <MoreSheet open={sheet === 'more'} onClose={() => setSheet(null)} s={s} dispatch={dispatch}
        ctx={{
          today, online, householdCurrency: data.householdCurrency, fuelCategoryId: data.fuelCategoryId,
          members: data.members, meId: data.meId, problems: v.problems,
        }} />
      <ConfirmSheet open={blocker.state === 'blocked'} title="Discard this entry?" confirmLabel="Discard"
        cancelLabel="Keep editing" danger onConfirm={() => blocker.proceed?.()} onCancel={() => blocker.reset?.()} />
    </div>
  )
}
