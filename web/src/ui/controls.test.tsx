import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Chips } from './Chips'
import { Toggle } from './Toggle'

const OPTIONS = [
  { value: 'a', label: 'Alpha' },
  { value: 'b', label: 'Beta' },
] as const

afterEach(cleanup)

describe('Chips', () => {
  it('single select presses one chip and reports the new value', () => {
    const onChange = vi.fn()
    render(<Chips label="Period" options={[...OPTIONS]} value="a" onChange={onChange} />)
    expect(screen.getByRole('group', { name: 'Period' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Alpha' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Beta' })).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(screen.getByRole('button', { name: 'Beta' }))
    expect(onChange).toHaveBeenCalledWith('b')
    fireEvent.click(screen.getByRole('button', { name: 'Alpha' }))
    expect(onChange).toHaveBeenCalledTimes(1) // re-selecting the selected chip is a no-op
  })

  it('uses its own class names, not the 2c Chip kit’s .chips/.chip (the Insights picker clip and wobble)', () => {
    render(<Chips label="Period" options={[...OPTIONS]} value="a" onChange={() => {}} />)
    const group = screen.getByRole('group', { name: 'Period' })
    expect(group).toHaveClass('chipset')
    expect(group).not.toHaveClass('chips')
    for (const b of screen.getAllByRole('button')) {
      expect(b).toHaveClass('chipset__chip')
      expect(b).not.toHaveClass('chip')
    }
  })

  it('multi select toggles membership', () => {
    const onChange = vi.fn()
    render(<Chips multiple label="Budgets" options={[...OPTIONS]} value={['a']} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Alpha' }))
    expect(onChange).toHaveBeenLastCalledWith([])
    fireEvent.click(screen.getByRole('button', { name: 'Beta' }))
    expect(onChange).toHaveBeenLastCalledWith(['a', 'b'])
  })
})

describe('Toggle', () => {
  it('is a labelled switch that reports the next state', () => {
    const onChange = vi.fn()
    render(<Toggle label="Overdue" checked onChange={onChange} />)
    const sw = screen.getByRole('switch', { name: 'Overdue' })
    expect(sw).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(sw)
    expect(onChange).toHaveBeenCalledWith(false)
  })

  it('ignores taps while busy and when disabled', () => {
    const onChange = vi.fn()
    const { rerender } = render(<Toggle label="Push" checked={false} busy onChange={onChange} />)
    fireEvent.click(screen.getByRole('switch'))
    expect(screen.getByRole('switch')).toHaveAttribute('aria-busy', 'true')
    rerender(<Toggle label="Push" checked={false} disabled onChange={onChange} />)
    fireEvent.click(screen.getByRole('switch'))
    expect(onChange).not.toHaveBeenCalled()
  })
})
