import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { barPct, scaleMax, seriesColor } from './scale'
import { HBarList } from './HBarList'
import { StackBar } from './StackBar'

const eur = (n: number) => `€${n.toFixed(2)}`

afterEach(cleanup)

describe('scale', () => {
  it('never divides by zero', () => {
    expect(scaleMax([0, 0])).toBe(1)
    expect(scaleMax([])).toBe(1)
    expect(scaleMax([3, Number.NaN, 7])).toBe(7)
    expect(barPct(0, 1)).toBe(0)
    expect(barPct(-5, 10)).toBe(0)
    expect(barPct(5, 10)).toBe(50)
    expect(barPct(50, 10)).toBe(100)
  })
  it('cycles the six token colours', () => {
    expect(seriesColor(0)).toBe('var(--c1)')
    expect(seriesColor(6)).toBe('var(--c1)')
  })
})

describe('HBarList', () => {
  const rows = [
    { id: 'g', label: 'Groceries', value: 400 },
    { id: 'uncategorised', label: 'Uncategorised', value: 100 },
    { id: '__cash_not_logged__', label: 'Cash (not yet logged)', value: 45, hatched: true },
  ]

  it('prints every value and scales bars to the largest', () => {
    const { container } = render(<HBarList label="Where it went" rows={rows} format={eur} />)
    expect(screen.getByText('€400.00')).toBeInTheDocument()
    expect(screen.getByText('€45.00')).toBeInTheDocument()
    const fills = container.querySelectorAll<HTMLElement>('.hbars__fill')
    expect(fills[0].style.width).toBe('100%')
    expect(fills[1].style.width).toBe('25%')
  })

  it('hatched rows say "not logged" and are not tappable', () => {
    const onSelect = vi.fn()
    const { container } = render(<HBarList label="Where" rows={rows} format={eur} onSelect={onSelect} />)
    expect(screen.getByText('not logged')).toBeInTheDocument()
    expect(container.querySelector('.hbars__fill--hatched')).not.toBeNull()
    expect(screen.getAllByRole('button')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: /Uncategorised/ }))
    expect(onSelect).toHaveBeenCalledWith(rows[1])
  })

  it('draws an empty bar for a negative value', () => {
    const { container } = render(
      <HBarList label="Where" rows={[{ id: 'a', label: 'A', value: -20 }, { id: 'b', label: 'B', value: 10 }]} format={eur} />,
    )
    const fills = container.querySelectorAll<HTMLElement>('.hbars__fill')
    expect([fills[0].style.width, fills[1].style.width]).toEqual(['0%', '100%'])
  })

  it('survives an all-zero list', () => {
    const { container } = render(
      <HBarList label="Where" rows={[{ id: 'a', label: 'A', value: 0 }]} format={eur} />,
    )
    expect(container.innerHTML).not.toContain('NaN')
  })
})

describe('StackBar', () => {
  it('sizes segments by share and names them all', () => {
    const { container } = render(
      <StackBar
        label="How you paid"
        format={eur}
        segments={[
          { id: 'card', label: 'Card', value: 75 },
          { id: 'cash', label: 'Cash', value: 25 },
        ]}
      />,
    )
    expect(screen.getByRole('img', { name: 'How you paid: Card €75.00, Cash €25.00' })).toBeInTheDocument()
    const parts = container.querySelectorAll<HTMLElement>('.stackbar__seg')
    expect([parts[0].style.width, parts[1].style.width]).toEqual(['75%', '25%'])
  })

  it('names hatched segments "not logged" and keeps colour by index', () => {
    const { container } = render(
      <StackBar
        label="Paid"
        format={eur}
        segments={[
          { id: 'a', label: 'Zero', value: 0 },
          { id: 'b', label: 'Card', value: 50 },
          { id: 'c', label: 'Cash', value: 50, hatched: true },
        ]}
      />,
    )
    expect(screen.getByRole('img', { name: 'Paid: Card €50.00, Cash €50.00 (not logged)' })).toBeInTheDocument()
    const parts = container.querySelectorAll<HTMLElement>('.stackbar__seg')
    expect(parts[0].style.getPropertyValue('--bar')).toBe('var(--c2)')
  })

  it('draws an empty track for a zero total', () => {
    const { container } = render(<StackBar label="How you paid" format={eur} segments={[]} />)
    expect(container.querySelectorAll('.stackbar__seg')).toHaveLength(0)
    expect(container.innerHTML).not.toContain('NaN')
  })
})
