import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { focusables, trapTab } from '../../../../ui/focusTrap'
import { XIcon } from '../../../../ui/icons'
import { makeDetector } from './detector'
import './scanner.css'

/**
 * The barcode camera (pantry spec §4.3). This module is only ever loaded with a dynamic import, when Scan is
 * tapped, so neither it nor the decoder is in the main chunk.
 */
export interface ScannerProps {
  onDetect: (code: string) => void
  /** No camera API, no camera, or permission denied: the caller falls back to the typed barcode. */
  onUnavailable: () => void
  onClose: () => void
}

const SCAN_EVERY_MS = 150
const BARCODE = /^\d{6,14}$/

export function Scanner({ onDetect, onUnavailable, onClose }: ScannerProps) {
  const video = useRef<HTMLVideoElement>(null)
  const root = useRef<HTMLDivElement>(null)
  const closeBtn = useRef<HTMLButtonElement>(null)
  const cb = useRef({ onDetect, onUnavailable, onClose })
  useEffect(() => { cb.current = { onDetect, onUnavailable, onClose } })

  // Camera + decode loop. Every exit (a read, Close, unmount) stops the stream's tracks.
  useEffect(() => {
    let live = true
    let stream: MediaStream | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    const stop = () => {
      live = false
      clearTimeout(timer)
      stream?.getTracks().forEach((t) => t.stop())
      stream = null
    }
    ;(async () => {
      const media = globalThis.navigator?.mediaDevices
      if (!media?.getUserMedia) throw new Error('No camera API')
      const s = await media.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      })
      if (!live) {
        s.getTracks().forEach((t) => t.stop())
        return
      }
      stream = s
      const v = video.current
      if (!v) return
      v.srcObject = s
      await v.play()
      const detector = await makeDetector()
      const scan = async () => {
        if (!live) return
        try {
          if (v.readyState >= 2) {
            const found = (await detector.detect(v)).find((b) => BARCODE.test(b.rawValue))
            if (found && live) {
              stop()
              cb.current.onDetect(found.rawValue)
              return
            }
          }
        } catch {
          // A frame that can't be read yet; try the next one.
        }
        if (live) timer = setTimeout(() => void scan(), SCAN_EVERY_MS)
      }
      void scan()
    })().catch(() => {
      if (!live) return
      stop()
      cb.current.onUnavailable()
    })
    return stop
  }, [])

  // A modal over the Add sheet: focus starts on Close, Tab stays inside, Esc closes only the camera. The
  // capture-phase listener runs before the sheet's own document listener, and stops it.
  useEffect(() => {
    ;(closeBtn.current ?? (root.current && focusables(root.current)[0]))?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        cb.current.onClose()
      } else if (e.key === 'Tab' && root.current) {
        e.stopPropagation()
        trapTab(root.current, e)
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [])

  return createPortal(
    <div ref={root} className="bscan" role="dialog" aria-modal="true" aria-label="Scan barcode" tabIndex={-1}>
      <video ref={video} className="bscan__video" muted playsInline aria-hidden="true" />
      <div className="bscan__top">
        <button ref={closeBtn} type="button" className="bscan__btn" aria-label="Close" onClick={() => cb.current.onClose()}>
          <XIcon />
        </button>
        <h2 className="bscan__title">Scan barcode</h2>
        <span className="bscan__slot" />
      </div>
      <div className="bscan__box" aria-hidden="true"><span className="bscan__line" /></div>
      <p className="bscan__hint">Hold the barcode inside the box</p>
    </div>,
    document.body,
  )
}
