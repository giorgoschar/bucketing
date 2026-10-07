import { useEffect, useState } from 'react'
import { type DefaultsRecord, loadDefaults } from '../defaults'

export function useDefaults(hh: string): DefaultsRecord | undefined {
  const [rec, setRec] = useState<DefaultsRecord>()
  useEffect(() => {
    let live = true
    void loadDefaults(hh).then((r) => { if (live) setRec(r) })
    return () => { live = false }
  }, [hh])
  return rec
}
