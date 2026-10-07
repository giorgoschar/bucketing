import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { AmountDisplay } from './AmountDisplay'

afterEach(cleanup)

it('announces the spoken amount and opens the currency sheet', () => {
  const onCurrency = vi.fn()
  render(<AmountDisplay text="4.10" symbol="€" currency="EUR" spoken="Amount 4.10 euro" onCurrency={onCurrency} />)
  expect(screen.getByRole('status')).toHaveTextContent('Amount 4.10 euro')
  fireEvent.click(screen.getByRole('button', { name: 'Currency: EUR. Change' }))
  expect(onCurrency).toHaveBeenCalled()
})

it('shrinks above 9 characters, shows the converted line and the tag', () => {
  const { container } = render(
    <AmountDisplay text="1,234,567.8" symbol="£" currency="GBP" spoken="x" converted="≈ €23.06" tag="from receipt" />,
  )
  expect(container.querySelector('.amount__big--small')).not.toBeNull()
  expect(screen.getByText('≈ €23.06')).toBeInTheDocument()
  expect(screen.getByText('from receipt')).toBeInTheDocument()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('income tone', () => {
  const { container } = render(<AmountDisplay text="700" symbol="€" currency="EUR" spoken="x" tone="income" />)
  expect(container.querySelector('.amount--income')).not.toBeNull()
})
