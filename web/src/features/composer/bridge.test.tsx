import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { resetTestEnv } from '../../test/render'
import { afterTxnWrite, editKey, keys, merchantsKey, ToastHost, useComposerToast } from './bridge'

afterEach(resetTestEnv)

it("useComposerToast shows the text and its action through 2a's toast", () => {
  const onPress = vi.fn()
  render(<ToastHost />)
  const { result } = renderHook(() => useComposerToast())
  act(() => result.current({ text: 'Saved €3.00 to Day to day', action: { label: 'Undo', onPress } }))
  expect(screen.getByText('Saved €3.00 to Day to day')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Undo' }))
  expect(onPress).toHaveBeenCalled()
})

it('a transaction write makes transactions, matches, plan, home, buckets and insights stale; 2b keys sit under transactions', () => {
  expect(afterTxnWrite).toEqual([keys.transactions.all, keys.matches(), keys.plan.all, keys.home.all, keys.buckets(), keys.insights.all])
  expect(editKey('t9').slice(0, keys.transactions.all.length)).toEqual([...keys.transactions.all])
  expect(merchantsKey.slice(0, keys.transactions.all.length)).toEqual([...keys.transactions.all])
})
