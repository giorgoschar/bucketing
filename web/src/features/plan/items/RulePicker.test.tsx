import { fireEvent, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../../test/fakeApi'
import { renderWithProviders, resetTestEnv, setOnline } from '../../../test/render'
import { toRuleFields, type RuleChoice } from './rule'
import { RulePicker } from './RulePicker'

afterEach(resetTestEnv)

function Harness({ initial }: { initial: RuleChoice }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <RulePicker value={value} startDate="2026-10-01" endDate="" onChange={setValue} />
      <output data-testid="fields">{JSON.stringify(toRuleFields(value))}</output>
    </>
  )
}
const fields = () => JSON.parse(screen.getByTestId('fields').textContent!) as Record<string, unknown>
const start = (): RuleChoice => ({ kind: 'monthly_day', day: 1, adjust: 'none', everyMonths: 1 })
const preview = () => fakeApi({ 'POST /api/v1/recurring/preview': () => ({ dates: ['2026-10-26', '2026-11-25', '2026-12-23'] }) })
const repeats = (kind: string) => fireEvent.change(screen.getByLabelText('Repeats'), { target: { value: kind } })

it('day of the month with the business day before (the salary rule)', async () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  fireEvent.change(screen.getByLabelText('Day of the month'), { target: { value: '26' } })
  fireEvent.click(screen.getByRole('button', { name: 'Business day before' }))
  expect(fields()).toMatchObject({ rule_kind: 'monthly_day', rule_day: 26, rule_adjust: 'previous_business_day', interval_months: 1 })
  expect(screen.getByText('26th, or the business day before')).toBeInTheDocument()
  expect(await screen.findByText('Next: 26 Oct, 25 Nov, 23 Dec')).toBeInTheDocument()
})

it('last business day of the month has no fields', () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  repeats('last_business_day')
  expect(fields()).toEqual({
    rule_kind: 'last_business_day', interval_months: 1, rule_day: null, rule_month: null, rule_adjust: 'none',
    rule_days: null, rule_weekday: null, rule_interval_weeks: null,
  })
  expect(screen.queryByLabelText('Day of the month')).toBeNull()
})

it('every year on a date (the Christmas bonus)', () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  repeats('yearly')
  fireEvent.change(screen.getByLabelText('Day'), { target: { value: '21' } })
  fireEvent.change(screen.getByLabelText('Month'), { target: { value: '12' } })
  fireEvent.click(screen.getByRole('button', { name: 'Business day before' }))
  expect(fields()).toMatchObject({ rule_kind: 'yearly', rule_day: 21, rule_month: 12, rule_adjust: 'previous_business_day' })
})

it('Easter offset: before is a toggle, the days stay positive', () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  repeats('easter_offset')
  fireEvent.click(screen.getByRole('button', { name: 'Before' }))
  fireEvent.change(screen.getByLabelText('Days'), { target: { value: '4' } })
  expect(fields()).toMatchObject({ rule_kind: 'easter_offset', rule_days: -4 })
  fireEvent.click(screen.getByRole('button', { name: 'After' }))
  expect(fields()).toMatchObject({ rule_days: 4 })
})

it('every N weeks on a weekday, and every N months from the start date', () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  repeats('weekly')
  fireEvent.change(screen.getByLabelText('Weekday'), { target: { value: '4' } })
  fireEvent.change(screen.getByLabelText('Every how many weeks'), { target: { value: '2' } })
  expect(fields()).toMatchObject({ rule_kind: 'weekly', rule_weekday: 4, rule_interval_weeks: 2 })
  repeats('monthly_interval')
  fireEvent.change(screen.getByLabelText('Every how many months'), { target: { value: '3' } })
  expect(fields()).toMatchObject({ rule_kind: 'monthly_interval', interval_months: 3, rule_weekday: null })
})

it('an out-of-range number is refused with a hint and the last good value is kept', () => {
  preview()
  renderWithProviders(<Harness initial={start()} />)
  fireEvent.change(screen.getByLabelText('Day of the month'), { target: { value: '32' } })
  expect(screen.getByText('Enter 1 to 31')).toBeInTheDocument()
  expect(fields()).toMatchObject({ rule_day: 1 })
})

it('offline: the preview says it needs a connection', () => {
  fakeApi({})
  setOnline(false)
  renderWithProviders(<Harness initial={start()} />)
  expect(screen.getByText('Preview needs a connection')).toBeInTheDocument()
})
