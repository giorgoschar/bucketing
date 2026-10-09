import { useEffect, useId, useLayoutEffect, useReducer, useRef, useState } from 'react'
import { useBlocker, useNavigate, useSearchParams } from 'react-router'
import { CloseIcon } from '../../shell/icons'
import { AmountDisplay } from '../../ui/AmountDisplay'
import { Keypad } from '../../ui/Keypad'
import { DESKTOP_QUERY } from '../../ui/useIsDesktop'
import { Pill } from '../../ui/Pill'
import { type AmountKey, centsToString, convertCents, displayAmount, parseRate, toApiAmount, toCents } from './amount'
import { Segmented, type ToastInput, useComposerToast, useOfferTickedPrompt, useOnline } from './bridge'
import { CashControls } from './CashControls'
import { ConfirmSheet } from './ConfirmSheet'
import { currencyName, currencySymbol, formatCents, spokenMoney } from './currencies'
import { dayLabel, todayLocal } from './dates'
import { type DefaultsRecord, initialNew, matchRule, RULES_API_READY, sanitize, suggestMerchants } from './defaults'
import { dropDraft, parkDraft, parkedDraft } from './draft'
import { usePanel } from './panel'
import { DuplicateCard } from './DuplicateCard'
import { EditTopMenu } from './EditTopMenu'
import type { ComposerData } from './hooks/useComposerData'
import { useDuplicateCheck } from './hooks/useDuplicateCheck'
import { useReceiptUpload } from './hooks/useReceiptUpload'
import { useSaveTransaction } from './hooks/useSaveTransaction'
import { useUndoCreate } from './hooks/undo'
import { firstProblem, isDirtyNew, isFuel, moreDirty, toUpdateBody, validate } from './model'
import { MoreSheet } from './MoreSheet'
import { ReviewBanner } from './scan/ReviewBanner'
import { ScanScreen } from './scan/ScanScreen'
import { SplitSheet } from './SplitSheet'
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

type SheetName = 'bucket' | 'category' | 'payer' | 'method' | 'currency' | 'date' | 'more' | 'split' | 'own'

const QUEUED = "Saved on this phone. It will sync when you're back online."
const QUEUED_NO_RECEIPT = "Saved on this phone. The receipt wasn't attached: add it when you're back online."
const UPLOAD_FAILED = "Saved. The receipt didn't upload."
const UNDO_MS = 5000
const INTERACTIVE = 'button, a[href], select, summary, [role="button"], [role="option"], [role="switch"], [role="tab"], [role="menuitem"], [role="link"]'

/** A modal sheet is open anywhere (they portal out, so their keys still bubble through this tree). */
const modalOpen = () => !!document.querySelector('[aria-modal="true"], dialog[open]')

type Note = { text: string; undoId?: string }

export function ComposerForm({ initial, data, defaults, draftKey = 'new' }: {
  initial: ComposerState; data: ComposerData; defaults: DefaultsRecord; draftKey?: string
}) {
  const panel = usePanel()
  // A form parked by the window crossing 1024 px (draft.ts) is picked up here; `initial` stays the baseline for "changed".
  const [s, dispatch] = useReducer(reduce, initial, (i) => parkedDraft(draftKey) ?? i)
  useEffect(() => { dropDraft(draftKey) }, [draftKey])
  const amountRef = useRef<HTMLInputElement>(null)
  const [note, setNote] = useState<Note | null>(null)
  const [confirmClose, setConfirmClose] = useState(false)
  const today = todayLocal()
  const online = useOnline()
  const navigate = useNavigate()
  const close = useClose()
  const toast = useComposerToast()
  const offerPantry = useOfferTickedPrompt()
  const ctx = { hh: data.hh, householdCurrency: data.householdCurrency, fuelCategoryId: data.fuelCategoryId, meId: data.meId }
  const save = useSaveTransaction(s, ctx, defaults, initial.mode === 'edit' && initial.method === 'cash')
  const checkDuplicate = useDuplicateCheck()
  const upload = useReceiptUpload()
  const undo = useUndoCreate()
  const [sheet, setSheet] = useState<SheetName | null>(null)
  const [dup, setDup] = useState<Duplicate | null>(null)
  const [typing, setTyping] = useState(false)
  // Merchant combobox: the highlighted suggestion (-1 none) and whether Escape closed the list.
  const [active, setActive] = useState(-1)
  const [listClosed, setListClosed] = useState(false)
  const listId = useId()
  const [stashCents, setStashCents] = useState<number | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const splitTyped = useRef<Record<string, string>>({})
  // The scan overlay is ?mode=scan, replaced in place: Back and Save still return to where the composer opened.
  const [params, setParams] = useSearchParams()
  const scanOpen = params.get('mode') === 'scan'
  const setScan = (open: boolean) =>
    setParams((p) => {
      if (open) p.set('mode', 'scan')
      else p.delete('mode')
      return p
    }, { replace: true })
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
    const edit = to && /^\/edit\/([^/?]+)/.exec(to)
    if (panel && edit) panel.openEdit(decodeURIComponent(edit[1]))
    else if (to) void navigate(to, { replace: true })
    else close()
  }
  // The panel closes by changing only the query, which the blocker above doesn't see: ask here instead.
  const requestClose = () => (dirty && !leaving.current ? setConfirmClose(true) : close())

  // Crossing 1024 px unmounts this form and mounts the other layout's: park what was typed for it.
  const latest = useRef({ s, dirty })
  useEffect(() => { latest.current = { s, dirty } })
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mql = window.matchMedia(DESKTOP_QUERY)
    const onCross = () => {
      if (latest.current.dirty && !leaving.current) parkDraft(draftKey, latest.current.s)
    }
    mql.addEventListener('change', onCross)
    return () => mql.removeEventListener('change', onCross)
  }, [draftKey])

  // Esc closes the panel (a sheet, a field's own list or the scan screen takes its own Esc first).
  const closeRef = useRef(requestClose)
  useEffect(() => { closeRef.current = requestClose })
  useEffect(() => {
    if (!panel) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented || modalOpen() || document.querySelector('.scan')) return
      e.preventDefault()
      closeRef.current()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [panel])

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

  // The panel stays open after an add (spec §4.5): a new entry that keeps the date, budget and payer, a line saying
  // what was saved, and the Undo the toast would have had.
  function stayOpen(r: { status: string; id?: string }, receipt: File | null) {
    const queued = r.status === 'queued'
    const merchant = s.merchant.trim()
    setNote(queued
      ? { text: receipt ? QUEUED_NO_RECEIPT : QUEUED }
      : { text: `Saved · ${money}${merchant ? ` ${merchant}` : ''}`, undoId: r.id })
    if (!queued && r.id) {
      if (s.type === 'expense') offerPantry()
      if (receipt) void uploadReceipt(r.id, receipt)
    }
    const fresh = initialNew({
      defaults, buckets: data.buckets, categories: data.categories, memberIds, meId: data.meId,
      householdCurrency: data.householdCurrency, type: s.type, today, clientId: crypto.randomUUID(),
      cash: false, amount: null, take: null,
    })
    dispatch({ type: 'replace', state: { ...fresh, date: s.date, bucketId: s.bucketId, paidBy: s.paidBy ?? fresh.paidBy } })
    setDup(null)
    setStashCents(null)
    amountRef.current?.focus()
  }

  // The Undo lasts as long as the toast's would.
  useEffect(() => {
    if (!note?.undoId) return
    const t = setTimeout(() => setNote({ text: note.text }), UNDO_MS)
    return () => clearTimeout(t)
  }, [note])

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
      if (panel && s.mode === 'new') {
        stayOpen(r, receipt)
        return
      }
      leave()
      if (r.status === 'queued') {
        toast({ text: receipt ? QUEUED_NO_RECEIPT : QUEUED })
        return
      }
      toast(savedToast(r.id))
      // Pantry spec §4.6: a new expense saved online may prompt for ticked items. Fire and forget: never awaited.
      if (s.mode === 'new' && s.type === 'expense') offerPantry()
      if (receipt) void uploadReceipt(r.id, receipt)
    } finally {
      submitting.current = false
    }
  }

  // Fuel prefill (spec §4.6), keyed on the category so a price the user cleared stays cleared.
  useEffect(() => {
    if (s.mode === 'new' && isFuel(s, ctx) && s.fuelPrice === '' && defaults.fuelPrice) {
      dispatch({ type: 'setFuelPrice', value: defaults.fuelPrice })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.categoryId])

  async function onDelete() {
    setConfirmDelete(false)
    const r = await save.deleteEntry()
    if (r.status === 'done' || r.status === 'queued') {
      leave()
      toast({ text: r.status === 'queued' ? QUEUED : 'Deleted' })
    }
  }

  // Hardware keyboard (spec §4.2): digits, "." or ",", Backspace, Enter saves. Not while a field or sheet has focus,
  // and Enter on a focused button, link or control activates that control instead (✕ must close, not save).
  // A layout effect: the listener is live before the first paint, so an early keystroke is never lost.
  const onSaveRef = useRef(onSave)
  useEffect(() => { onSaveRef.current = onSave })
  useLayoutEffect(() => {
    if (panel) return // the panel's amount is a text field; Enter and Esc are handled below
    const onKeyDown = (e: KeyboardEvent) => {
      if (sheet || dup || confirmDelete || scanOpen || blocker.state === 'blocked') return
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      let key: AmountKey | null = null
      if (/^[0-9]$/.test(e.key)) key = e.key as AmountKey
      else if (e.key === '.' || e.key === ',') key = '.'
      else if (e.key === 'Backspace') key = 'back'
      if (key) dispatch({ type: 'key', key })
      else if (e.key === 'Enter') {
        if (t?.closest?.(INTERACTIVE)) return
        void onSaveRef.current()
      }
      else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [panel, sheet, dup, confirmDelete, scanOpen, blocker.state])

  const switchType = (value: TxnType) => {
    const r = sanitize(value === 'income' ? defaults.lastIncome : defaults.last, lookup(value))
    dispatch({ type: 'setType', value, defaults: { ...r, paid_by: r.paid_by ?? data.meId } })
  }
  const toggleCash = () =>
    dispatch({ type: 'setCashMode', on: !s.cashMode, meId: data.meId, defaultMethod: remembered(defaults.last).payment_method ?? 'card' })

  const rule = matchRule(s.merchant, data.rules)
  const suggestions = typing && !listClosed ? suggestMerchants(s.merchant, data.merchants) : []
  const setMerchant = (value: string) => {
    setActive(-1)
    setListClosed(false)
    dispatch({ type: 'setMerchant', value, rule: matchRule(value, data.rules) })
  }
  const onMerchantKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const n = suggestions.length
    if (e.key === 'ArrowDown' && n) {
      e.preventDefault()
      setActive((a) => (a + 1) % n)
    } else if (e.key === 'ArrowUp' && n) {
      e.preventDefault()
      setActive((a) => (a <= 0 ? n - 1 : a - 1))
    } else if (e.key === 'Escape' && n) {
      e.preventDefault()
      setListClosed(true)
      setActive(-1)
    } else if (e.key === 'Enter') {
      if (active >= 0 && active < n) {
        e.preventDefault()
        const pick = suggestions[active]
        setMerchant(pick)
        setListClosed(true)
      } else if (!panel) {
        e.preventDefault()
        ;(e.target as HTMLInputElement).blur()
      } // in the panel Enter saves (onPanelKey)
    }
  }

  // Panel keyboard (spec §4.5): Enter saves from a field, ⌘/Ctrl+Enter from anywhere. A focused button, link or
  // picker row keeps its own Enter; so does the notes textarea; sheets (portalled) and the scan screen their own.
  const onPanelKey = (e: React.KeyboardEvent) => {
    if (e.key !== 'Enter' || e.defaultPrevented || e.nativeEvent.isComposing || modalOpen() || scanOpen) return
    const t = e.target as HTMLElement
    if (!(e.metaKey || e.ctrlKey) && (t.closest(INTERACTIVE) || t.tagName === 'TEXTAREA')) return
    e.preventDefault()
    void onSave()
  }
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
  const allowOwnShare = !income && data.members.length > 1 && s.tookFrom === 'none' && !s.cashMode

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

  const typeSwitch = (
    <Segmented label="Entry type" value={s.type} onChange={switchType} disabled={s.mode === 'edit'}
      options={[{ value: 'expense', label: 'Expense' }, { value: 'income', label: 'Income' }]} />
  )
  const slot = (
    <span className="composer__slot">
      {!online && <span className="composer__offline">Offline</span>}
      {s.mode === 'edit' && <EditTopMenu onDelete={() => setConfirmDelete(true)} />}
    </span>
  )
  const modes = s.mode === 'new' && !income && (
    <div className="composer__modes" role="group" aria-label="Entry mode">
      <button type="button" className="ck-chip" onClick={() => setScan(true)}>Scan receipt</button>
      <button type="button" className={s.cashMode ? 'ck-chip on' : 'ck-chip'} aria-pressed={s.cashMode} onClick={toggleCash}>
        Cash from wallet
      </button>
    </div>
  )
  const amountField = panel ? (
    <div className={income ? 'amount amount--income panelamount' : 'amount panelamount'}>
      <span className="panelamount__symbol" aria-hidden="true">{currencySymbol(s.currency)}</span>
      <input ref={amountRef} className="panelamount__input" aria-label="Amount" inputMode="decimal" autoComplete="off"
        placeholder="0.00" autoFocus value={s.amount} onChange={(e) => dispatch({ type: 'setAmount', value: e.target.value })} />
      <button type="button" className="amount__cur" onClick={() => setSheet('currency')}
        aria-label={`Currency: ${s.currency}. Change`}>
        {s.currency}
      </button>
      {converted && <p className="amount__converted">{converted}</p>}
      {s.fromReceipt.includes('amount') && <span className="amount__tag">from receipt</span>}
    </div>
  ) : (
    <AmountDisplay text={displayAmount(s.amount)} symbol={currencySymbol(s.currency)} currency={s.currency}
      spoken={`Amount ${centsToString(cents)} ${currencyName(s.currency)}`} tone={income ? 'income' : 'default'}
      converted={converted} onCurrency={() => setSheet('currency')}
      tag={s.fromReceipt.includes('amount') ? 'from receipt' : null} />
  )

  return (
    <div className={panel ? 'composer composer--panel' : 'composer'} data-type={s.type} onKeyDown={panel ? onPanelKey : undefined}>
      <header className="composer__bar">
        {panel ? (
          <>
            <h2 className="composer__title">{s.mode === 'edit' ? 'Edit entry' : 'New entry'}</h2>
            {slot}
            <button type="button" className="ui-iconbtn composer__close" aria-label="Close" onClick={requestClose}>
              <CloseIcon />
            </button>
          </>
        ) : (
          <>
            <button type="button" className="ui-iconbtn composer__close" aria-label="Close" onClick={close}>
              <CloseIcon />
            </button>
            {typeSwitch}
            {slot}
          </>
        )}
      </header>

      <div className="composer__body">
        {!panel && modes}

        <ReviewBanner s={s} categories={data.categories} rulesReady={RULES_API_READY}
          onRemember={(on) => dispatch({ type: 'setRemember', on })} />
        {amountField}
        {panel && typeSwitch}
        {s.scanNoTotal && <p className="composer__hint">Couldn't find the total</p>}

        <div className="composer__merchant-wrap">
          <input className="composer__merchant" aria-label="Merchant" placeholder="Where? (optional)" maxLength={100}
            role="combobox" aria-autocomplete="list" aria-expanded={suggestions.length > 0}
            aria-controls={suggestions.length > 0 ? listId : undefined}
            aria-activedescendant={active >= 0 && active < suggestions.length ? `${listId}-${active}` : undefined}
            autoComplete="off" autoCorrect="off" enterKeyHint="done" value={s.merchant}
            onChange={(e) => setMerchant(e.target.value)}
            onFocus={() => setTyping(true)}
            onBlur={() => { setTyping(false); setActive(-1); setListClosed(false) }}
            onKeyDown={onMerchantKey} />
          {suggestions.length > 0 && (
            <ul id={listId} className="composer__suggest" role="listbox" aria-label="Recent places">
              {suggestions.map((m, i) => (
                <li key={m} id={`${listId}-${i}`} role="option" aria-selected={i === active}
                  className={i === active ? 'composer__suggest-item is-active' : 'composer__suggest-item'}
                  // mousedown keeps the input focused so the pick lands before blur hides the list.
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => setMerchant(m)}>
                  {m}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="pills composer__pills">
          {panel ? (
            // The panel's Tab order (spec §4.5): budget, category, payer, method, date.
            <>
              {budgetPill}
              {categoryPill}
              {income
                ? <Pill label="Received by" value={memberName(payer)} onPress={() => setSheet('payer')} />
                : <Pill label="Payer" value={payerValue} readOnly={s.cashMode} onPress={() => setSheet('payer')} />}
              {!income && <Pill label="Method" value={METHOD_LABELS[s.method]} onPress={() => setSheet('method')} />}
              <Pill label="Date" value={dayLabel(s.date, today)} onPress={() => setSheet('date')} />
            </>
          ) : income ? (
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
        {panel && modes}
      </div>

      <div className="composer__foot">
        {hint && <p className="composer__problem">{hint}</p>}
        {panel && note && (
          <p className="composer__saved" role="status">
            <span>{note.text}</span>
            {note.undoId && (
              <button type="button" className="composer__undo"
                onClick={() => { void undo(note.undoId!); setNote({ text: 'Undone' }) }}>
                Undo
              </button>
            )}
          </p>
        )}
        {!panel && <Keypad onKey={(k) => dispatch({ type: 'key', key: k })} hidden={typing} />}
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
          onPick={(id) => dispatch({ type: 'pickPayer', id })} onOwnShare={() => setSheet('own')} />
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
          members: data.members, meId: data.meId, problems: v.problems, onOpenSplit: () => setSheet('split'),
        }} />
      <SplitSheet open={sheet === 'split' || sheet === 'own'} variant={sheet === 'own' ? 'own' : 'split'} totalCents={cents}
        currency={s.currency} members={data.members} payerId={s.paidBy} initial={{ mode: s.splitMode, shares: s.splits, typed: (sheet === 'own' ? s.ownShare : s.splitOn) ? s.splitTyped : undefined }}
        onTyped={(t) => { splitTyped.current = t }}
        onDone={(r) => {
          const typed = splitTyped.current
          dispatch(sheet === 'own' ? { type: 'setOwnShare', splits: r.shares, typed } : { type: 'setSplit', on: true, mode: r.mode, splits: r.shares, typed })
        }}
        onClose={() => setSheet(sheet === 'split' ? 'more' : null)} />
      {scanOpen && (
        <ScanScreen
          online={online}
          onResult={(r) => {
            dispatch({ type: 'applyScan', result: r, householdCurrency: data.householdCurrency, today })
            setScan(false)
          }}
          onPhoto={(file) => {
            dispatch({ type: 'attachPhoto', file })
            setScan(false)
          }}
          onClose={() => setScan(false)}
        />
      )}
      <ConfirmSheet open={blocker.state === 'blocked'} title="Discard this entry?" confirmLabel="Discard"
        cancelLabel="Keep editing" danger onConfirm={() => blocker.proceed?.()} onCancel={() => blocker.reset?.()} />
      <ConfirmSheet open={confirmClose} title="Discard this entry?" confirmLabel="Discard"
        cancelLabel="Keep editing" danger onConfirm={() => { leaving.current = true; setConfirmClose(false); close() }}
        onCancel={() => setConfirmClose(false)} />
      <ConfirmSheet open={confirmDelete} title="Delete this entry?" confirmLabel="Delete" cancelLabel="Cancel" danger
        onConfirm={() => void onDelete()} onCancel={() => setConfirmDelete(false)} />
    </div>
  )
}
