import { screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { fakeApi } from '../../test/fakeApi'
import { yearMonth, yearOut } from '../../test/fixtures'
import { renderWithProviders, resetTestEnv } from '../../test/render'
import { Year } from './Year'

afterEach(resetTestEnv)

const widths = (cls: string) =>
  Array.from(document.querySelectorAll<HTMLElement>(`.${cls}`)).map((el) => el.style.width)

it('scales both bars to the largest value of the year and writes the values out', async () => {
  fakeApi({
    'GET /api/v1/plan/year': () =>
      yearOut([yearMonth('2026-10', 3000, 1500), yearMonth('2026-11', 1500, 3000, true), yearMonth('2026-12', 0, 0)]),
  })
  renderWithProviders(<Year />)
  const oct = (await screen.findByText('Oct')).closest('li')!
  expect(oct).toHaveTextContent('In €3,000')
  expect(oct).toHaveTextContent('Out €1,500')
  expect(oct).toHaveTextContent('Net +€1,500')
  expect(widths('plan-year__bar--in')).toEqual(['100%', '50%', '0%'])
  expect(widths('plan-year__bar--out')).toEqual(['50%', '100%', '0%'])
  expect(screen.getByText('Nov').closest('li')).toHaveTextContent('Net ≈ −€1,500')
  expect(screen.getByText(/Yearly and quarterly bills average/)).toHaveTextContent('Yearly and quarterly bills average €42.50/month')
})

it('an all-zero year draws empty bars, not NaN', async () => {
  fakeApi({ 'GET /api/v1/plan/year': () => yearOut([yearMonth('2026-10', 0, 0), yearMonth('2026-11', 0, 0)]) })
  renderWithProviders(<Year />)
  await screen.findByText('Oct')
  expect(widths('plan-year__bar--in')).toEqual(['0%', '0%'])
  expect(document.body.textContent).not.toContain('NaN')
})
