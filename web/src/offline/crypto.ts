import { db, type Sealed } from './db'

let cached: Promise<CryptoKey> | null = null
let generation = 0

/** Bumped by every forgetKey()/wipe(); work started under an older generation must not persist anything. */
export function keyGeneration(): number { return generation }

export function forgetKey(): void {
  generation++
  cached = null
}

const stale = () => new Error('Device key was wiped while it was being created')

export function getKey(): Promise<CryptoKey> {
  if (cached) return cached
  const gen = generation
  const p = (async () => {
    const row = await db.keys.get('device')
    if (gen !== generation) throw stale()
    if (row) return row.key
    // Generate outside the transaction: WebCrypto awaits would auto-close an IndexedDB transaction.
    const fresh = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, [
      'encrypt',
      'decrypt',
    ])
    // Get-or-create atomically so concurrent tabs converge on a single stored key.
    const key = await db.transaction('rw', db.keys, async () => {
      const existing = await db.keys.get('device')
      if (existing) return existing.key
      if (gen !== generation) throw stale()
      await db.keys.add({ id: 'device', key: fresh })
      return fresh
    })
    if (gen !== generation) throw stale()
    return key
  })()
  cached = p
  p.catch(() => {
    if (cached === p) cached = null
  })
  return p
}

export async function seal(value: unknown): Promise<Sealed> {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const plain = new TextEncoder().encode(JSON.stringify(value))
  const data = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await getKey(), plain)
  return { iv, data }
}

export async function open<T>(rec: Sealed): Promise<T> {
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: rec.iv }, await getKey(), rec.data)
  return JSON.parse(new TextDecoder().decode(plain)) as T
}
