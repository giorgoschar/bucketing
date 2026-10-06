import { beforeEach, describe, expect, it, vi } from 'vitest'
import { forgetKey, getKey, open, seal } from './crypto'
import { db, wipe } from './db'

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

describe('crypto robustness', () => {
  it('recovers after a transient failure instead of caching the rejection', async () => {
    const spy = vi.spyOn(db.keys, 'get').mockRejectedValueOnce(new Error('boom'))
    await expect(getKey()).rejects.toThrow('boom')
    spy.mockRestore()
    expect((await getKey()).extractable).toBe(false)
  })

  it('a wipe during first-time key creation leaves no key row behind', async () => {
    const p = getKey().catch(() => undefined)
    await Promise.all([p, wipe()])
    expect(await db.keys.count()).toBe(0)
    const k = await getKey()
    expect(k.extractable).toBe(false)
    expect(await db.keys.count()).toBe(1)
  })

  it('two tabs creating the first key concurrently converge on one key', async () => {
    vi.resetModules()
    const tabA = await import('./crypto')
    vi.resetModules()
    const tabB = await import('./crypto')
    const [kA, kB] = await Promise.all([tabA.getKey(), tabB.getKey()])
    expect(kA).toBeDefined()
    const rec = await tabA.seal('shared')
    expect(await tabB.open(rec)).toBe('shared')
    expect(kB).toBeDefined()
    const dbB = (await import('./db')).db
    expect(await dbB.keys.count()).toBe(1)
  })

  it('reloads the persisted key from IndexedDB', async () => {
    const rec = await seal('persist')
    forgetKey()
    const k = await getKey()
    expect(k.extractable).toBe(false)
    expect(await open(rec)).toBe('persist')
  })
})
