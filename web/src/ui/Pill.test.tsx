import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { Pill } from './Pill'

afterEach(cleanup)

it('names itself "Label: value. Change" and reports a press', () => {
  const onPress = vi.fn()
  render(<Pill label="Budget" value="Day to day" onPress={onPress} />)
  fireEvent.click(screen.getByRole('button', { name: 'Budget: Day to day. Change' }))
  expect(onPress).toHaveBeenCalled()
})

it('empty is dashed, a tag is part of the name, read-only is not a button', () => {
  const { container, rerender } = render(<Pill label="Budget" value="Choose a budget" empty onPress={() => {}} />)
  expect(container.querySelector('.pill--empty')).not.toBeNull()
  rerender(<Pill label="Category" value="Coffee" tag="rule: coffee island" onPress={() => {}} />)
  expect(screen.getByRole('button', { name: 'Category: Coffee, rule: coffee island. Change' })).toBeInTheDocument()
  rerender(<Pill label="Payer" value="You" readOnly />)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  expect(screen.getByText('You')).toBeInTheDocument()
})
