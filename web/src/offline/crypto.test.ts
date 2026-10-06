import { beforeEach, describe, expect, it } from 'vitest'
import { getKey, open, seal } from './crypto'
import { wipe } from './db'

beforeEach(() => wipe())

describe('crypto', () => {
  it('round-trips a value', async () => {
    const rec = await seal({ amount: '64.20', note: 'Sklavenitis' })
    expect(await open(rec)).toEqual({ amount: '64.20', note: 'Sklavenitis' })
  })

  it('uses a fresh IV each time', async () => {
    const a = await seal('x'), b = await seal('x')
    expect(Array.from(a.iv)).not.toEqual(Array.from(b.iv))
  })

  it('stores ciphertext, not plaintext', async () => {
    const rec = await seal('Sklavenitis')
    expect(new TextDecoder().decode(rec.data)).not.toContain('Sklavenitis')
  })

  it('key is not extractable and is reused', async () => {
    const k1 = await getKey(), k2 = await getKey()
    expect(k1.extractable).toBe(false)
    expect(k1).toBe(k2)
  })

  it('wipe makes old records unreadable', async () => {
    const rec = await seal('secret')
    await wipe()
    await expect(open(rec)).rejects.toThrow()
  })
})
