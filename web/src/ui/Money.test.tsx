import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { Money } from './Money'

afterEach(cleanup)

it('renders the amount with tabular numerals', () => {
  render(<Money amount={38.9} />)
  expect(screen.getByText('€38.90')).toHaveClass('ui-money')
})

it('marks estimates with ≈ and signs when asked', () => {
  render(<Money amount={1500} signed estimated />)
  expect(screen.getByText('≈ +€1,500.00')).toBeInTheDocument()
})

it('never shows NaN: null and non-finite amounts show the fallback text', () => {
  render(<><Money amount={null} /><Money amount={Number.NaN} nullText="variable" /></>)
  expect(screen.getByText('—')).toBeInTheDocument()
  expect(screen.getByText('variable')).toBeInTheDocument()
  expect(document.body.textContent).not.toContain('NaN')
})

it('tone auto tints positive amounts only', () => {
  render(<><Money amount={10} tone="auto" /><Money amount={-10} tone="auto" /></>)
  expect(screen.getByText('€10.00')).toHaveClass('ui-pos')
  expect(screen.getByText('−€10.00')).not.toHaveClass('ui-pos')
})
