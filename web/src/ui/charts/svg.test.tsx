import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { LineChart, MonthBars } from './index'

afterEach(cleanup)

const eur = (n: number) => `€${n.toFixed(2)}`
const MONTHS = ['May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct']

describe('MonthBars', () => {
  it('has a table with every value for two series', () => {
    render(
      <MonthBars
        title="In and Out by month"
        months={MONTHS}
        series={[
          { name: 'In', values: [3000, 3000, 3100, 3000, 3000, 1500] },
          { name: 'Out', values: [2180, 2410, 2050, 2960, 2240, 1284.6] },
        ]}
        format={eur}
        current
      />,
    )
    const table = screen.getByRole('table', { name: 'In and Out by month' })
    expect(within(table).getAllByRole('row')).toHaveLength(7)
    expect(within(table).getByRole('rowheader', { name: 'Oct (so far)' })).toBeInTheDocument()
    expect(within(table).getByText('€1284.60')).toBeInTheDocument()
  })

  it('draws one bar per month per series and labels the largest', () => {
    const { container } = render(
      <MonthBars title="Spend" months={MONTHS} series={[{ name: 'Spend', values: [1, 2, 9, 3, 4, 5] }]} format={eur} />,
    )
    expect(container.querySelectorAll('svg rect.chart__bar')).toHaveLength(6)
    expect(container.querySelector('svg text.chart__max')?.textContent).toBe('€9.00')
  })

  it('survives an all-zero series', () => {
    const { container } = render(
      <MonthBars title="Spend" months={MONTHS} series={[{ name: 'Spend', values: [0, 0, 0, 0, 0, 0] }]} format={eur} />,
    )
    expect(container.innerHTML).not.toContain('NaN')
    expect(container.querySelector('svg text.chart__max')).toBeNull()
  })
})

describe('LineChart', () => {
  const points = [1.79, 1.82, 1.86, 1.88, 1.83, 1.859].map((v, i) => ({ label: `Fill ${i + 1}`, value: v }))
  const per = (n: number) => `€${n.toFixed(3)}`

  it('has a table and prints the first and last values', () => {
    const { container } = render(<LineChart title="Price per litre" points={points} format={per} average={1.84} />)
    expect(screen.getByRole('table', { name: 'Price per litre' })).toBeInTheDocument()
    const labels = [...container.querySelectorAll('svg text')].map((t) => t.textContent)
    expect(labels).toEqual(expect.arrayContaining(['€1.790', '€1.859', 'avg €1.840']))
    expect(container.querySelectorAll('svg circle')).toHaveLength(6)
  })

  it('survives one point and a flat series', () => {
    const one = render(<LineChart title="P" points={[{ label: 'a', value: 2 }]} format={per} />)
    expect(one.container.innerHTML).not.toContain('NaN')
    const flat = render(<LineChart title="Q" points={[{ label: 'a', value: 0 }, { label: 'b', value: 0 }]} format={per} />)
    expect(flat.container.innerHTML).not.toContain('NaN')
  })
})
