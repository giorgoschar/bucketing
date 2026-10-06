import { db, type Sealed } from './db'

let cached: Promise<CryptoKey> | null = null

export function forgetKey(): void { cached = null }

export function getKey(): Promise<CryptoKey> {
  cached ??= (async () => {
    const row = await db.keys.get('device')
    if (row) return row.key
    const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, [
      'encrypt',
      'decrypt',
    ])
    await db.keys.put({ id: 'device', key })
    return key
  })()
  return cached
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
