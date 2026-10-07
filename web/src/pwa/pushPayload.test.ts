import { describe, expect, it } from 'vitest'
import { noticeFromPush } from './pushPayload'

describe('noticeFromPush', () => {
  it('maps the server payload', () => {
    const n = noticeFromPush(JSON.stringify({ title: 'Auto-paid: Cosmote', body: '€38.90 marked as paid', link: '/bills' }))
    expect(n.title).toBe('Auto-paid: Cosmote')
    expect(n.options.body).toBe('€38.90 marked as paid')
    expect(n.options.data.url).toBe('/app/plan')
    expect(n.options.icon).toBe('/app/icons/icon-192.png')
  })
  it('survives an empty or non-JSON push', () => {
    expect(noticeFromPush(null)).toMatchObject({ title: 'Tameio', options: { body: '', data: { url: '/app/' } } })
    expect(noticeFromPush('plain text').options.body).toBe('plain text')
    expect(noticeFromPush('42').options.body).toBe('') // valid JSON, not an object
  })
})
