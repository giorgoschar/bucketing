import { useId, useState } from 'react'
import { formatMonthName, formatShortDate } from '../../../ui/format'
import { Segmented } from '../../../ui/Segmented'
import { useRulePreview, type PreviewState } from './hooks'
import {
  ADJUST_LABELS, defaultChoice, RULE_ADJUSTS, RULE_KINDS, RULE_LABELS, ruleSummary, WEEKDAYS,
  type RuleAdjust, type RuleChoice, type RuleKind,
} from './rule'
import './items.css'

export interface RulePickerProps {
  value: RuleChoice
  startDate: string
  endDate: string
  onChange: (next: RuleChoice) => void
}

const ADJUST_OPTIONS = RULE_ADJUSTS.map((a) => ({ value: a, label: ADJUST_LABELS[a] }))
const SIDES = [{ value: 'before', label: 'Before' }, { value: 'after', label: 'After' }] as const

export function previewText(p: PreviewState): string {
  switch (p.state) {
    case 'offline': return 'Preview needs a connection'
    case 'loading': return 'Checking the dates…'
    case 'error': return p.message
    case 'ready': return p.dates.length ? `Next: ${p.dates.map(formatShortDate).join(', ')}` : 'No dates after today'
  }
}

export function RulePicker({ value, startDate, endDate, onChange }: RulePickerProps) {
  const preview = useRulePreview(value, startDate, endDate)
  return (
    <div className="items-rule">
      <label className="ui-field">
        <span className="ui-field__label">Repeats</span>
        <select className="ui-input" value={value.kind}
          onChange={(e) => onChange(defaultChoice(e.target.value as RuleKind, startDate))}>
          {RULE_KINDS.map((k) => <option key={k} value={k}>{RULE_LABELS[k]}</option>)}
        </select>
      </label>
      <KindFields value={value} onChange={onChange} />
      <p className="items-rule__summary">{ruleSummary(value, startDate)}</p>
      <p className="items-rule__preview" aria-live="polite">{previewText(preview)}</p>
    </div>
  )
}

function KindFields({ value: v, onChange }: { value: RuleChoice; onChange: (c: RuleChoice) => void }) {
  switch (v.kind) {
    case 'monthly_day':
      return (
        <>
          <NumberField label="Day of the month" value={v.day} min={1} max={31} onChange={(day) => onChange({ ...v, day })} />
          <AdjustField value={v.adjust} onChange={(adjust) => onChange({ ...v, adjust })} />
        </>
      )
    case 'last_business_day':
      return null
    case 'yearly':
      return (
        <>
          <div className="items-rule__row">
            <NumberField label="Day" value={v.day} min={1} max={31} onChange={(day) => onChange({ ...v, day })} />
            <label className="ui-field">
              <span className="ui-field__label">Month</span>
              <select className="ui-input" value={v.month} onChange={(e) => onChange({ ...v, month: Number(e.target.value) })}>
                {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{formatMonthName(i + 1)}</option>)}
              </select>
            </label>
          </div>
          <AdjustField value={v.adjust} onChange={(adjust) => onChange({ ...v, adjust })} />
        </>
      )
    case 'easter_offset':
      return <EasterFields value={v} onChange={onChange} />
    case 'weekly':
      return (
        <div className="items-rule__row">
          <label className="ui-field">
            <span className="ui-field__label">Weekday</span>
            <select className="ui-input" value={v.weekday} onChange={(e) => onChange({ ...v, weekday: Number(e.target.value) })}>
              {WEEKDAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}
            </select>
          </label>
          <NumberField label="Every how many weeks" value={v.everyWeeks} min={1} max={52}
            onChange={(everyWeeks) => onChange({ ...v, everyWeeks })} />
        </div>
      )
    case 'monthly_interval':
      return (
        <NumberField label="Every how many months" value={v.everyMonths} min={1} max={120}
          onChange={(everyMonths) => onChange({ ...v, everyMonths })} />
      )
  }
}

function EasterFields({ value: v, onChange }: { value: Extract<RuleChoice, { kind: 'easter_offset' }>; onChange: (c: RuleChoice) => void }) {
  // Kept apart from `days` so "Before" sticks while days is still 0.
  const [before, setBefore] = useState(v.days < 0)
  const days = Math.abs(v.days)
  return (
    <>
      <div className="items-rule__row">
        <NumberField label="Days" value={days} min={0} max={120} onChange={(n) => onChange({ ...v, days: before ? -n : n })} />
        <div className="ui-field">
          <span className="ui-field__label" aria-hidden="true">Before or after Easter</span>
          <Segmented label="Before or after Easter" options={SIDES} value={before ? 'before' : 'after'}
            onChange={(side) => {
              const b = side === 'before'
              setBefore(b)
              onChange({ ...v, days: b ? -days : days })
            }} />
        </div>
      </div>
      <AdjustField value={v.adjust} onChange={(adjust) => onChange({ ...v, adjust })} />
    </>
  )
}

function AdjustField({ value, onChange }: { value: RuleAdjust; onChange: (a: RuleAdjust) => void }) {
  return (
    <div className="ui-field">
      <span className="ui-field__label" aria-hidden="true">If it falls on a weekend or holiday</span>
      <Segmented label="If it falls on a weekend or holiday" options={ADJUST_OPTIONS} value={value} onChange={onChange} />
    </div>
  )
}

function NumberField({ label, value, min, max, onChange }: {
  label: string; value: number; min: number; max: number; onChange: (n: number) => void
}) {
  const id = useId()
  const [text, setText] = useState(String(value))
  const [synced, setSynced] = useState(value)
  if (value !== synced) {
    // The value changed from outside (another kind picked): show it.
    setSynced(value)
    setText(String(value))
  }
  const n = Number(text)
  const valid = text.trim() !== '' && Number.isInteger(n) && n >= min && n <= max
  return (
    <div className="ui-field">
      <label className="ui-field__label" htmlFor={id}>{label}</label>
      <input id={id} className="ui-input ui-num" inputMode="numeric" pattern="[0-9]*" autoComplete="off"
        value={text} aria-invalid={!valid}
        onChange={(e) => {
          const t = e.target.value
          setText(t)
          const k = Number(t)
          if (t.trim() !== '' && Number.isInteger(k) && k >= min && k <= max) {
            setSynced(k)
            onChange(k)
          }
        }} />
      {!valid && <p className="ui-field__error">{`Enter ${min} to ${max}`}</p>}
    </div>
  )
}
