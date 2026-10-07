import { useCallback, useEffect, useRef, useState } from 'react'
import { CloseIcon } from '../../../shell/icons'
import { trapTab } from '../../../ui/focusTrap'
import { Segmented } from '../bridge'
import { RECEIPT_ACCEPT, receiptProblem } from '../receipt'
import type { QrReceipt } from '../types'
import { shrinkImage } from './image'
import { isReceiptUrl, type QrSession, startQr } from './qr'
import { useQrLookup } from './useQrLookup'
import './scan.css'

export interface ScanScreenProps {
  online: boolean
  onResult: (r: QrReceipt) => void
  onPhoto: (file: File) => void
  onClose: () => void
}

type Mode = 'qr' | 'photo'
const MODES = [{ value: 'qr', label: 'QR' }, { value: 'photo', label: 'Photo' }] as const
const OFFLINE = 'Scanning needs a connection. Type it instead'

/** Full-screen scan (spec §4.7): the myDATA QR is looked up with AADE; Photo only attaches the image. */
export function ScanScreen({ online, onResult, onPhoto, onClose }: ScanScreenProps) {
  const [mode, setMode] = useState<Mode>('qr')
  const [camera, setCamera] = useState<'ok' | 'unavailable'>('ok')
  const [fileProblem, setFileProblem] = useState<string | null>(null)
  const video = useRef<HTMLVideoElement>(null)
  const closeBtn = useRef<HTMLButtonElement>(null)
  const root = useRef<HTMLDivElement>(null)
  const lookup = useQrLookup()
  const busy = useRef(false)
  const lastFailed = useRef<string | null>(null)
  const [message, setMessage] = useState<{ text: string; hint?: string } | null>(null)
  const [looking, setLooking] = useState(false)

  // The parent passes inline callbacks; keep them in refs so a parent re-render never restarts the camera.
  const onResultRef = useRef(onResult)
  const onPhotoRef = useRef(onPhoto)
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onResultRef.current = onResult
    onPhotoRef.current = onPhoto
    onCloseRef.current = onClose
  })

  const onDecode = useCallback(async (text: string) => {
    if (busy.current || text === lastFailed.current) return
    if (!isReceiptUrl(text)) {
      setMessage({ text: 'That is not a receipt QR' })
      return
    }
    busy.current = true
    setLooking(true)
    const r = await lookup(text.trim())
    busy.current = false
    setLooking(false)
    if (r.status === 'ok') return onResultRef.current(r.data)
    lastFailed.current = text
    setMessage({ text: r.message, hint: 'No QR? Use Photo to attach the receipt' })
  }, [lookup])

  useEffect(() => {
    if (mode !== 'qr' || !online || !video.current) return
    let session: QrSession | null = null
    let live = true
    startQr(video.current, (t) => void onDecode(t)).then(
      (s) => { if (live) session = s; else s.stop() },
      () => { if (live) setCamera('unavailable') },
    )
    return () => {
      live = false
      session?.stop()
    }
  }, [mode, online, onDecode]) // onDecode is stable (lookup is a stable useCallback)

  // A modal: focus starts on Close, Tab stays inside, Escape leaves.
  useEffect(() => {
    closeBtn.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onCloseRef.current()
      } else if (root.current) trapTab(root.current, e)
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
    }
  }, [])

  async function attach(file: File | undefined, kind: 'photo' | 'upload') {
    if (!file) return
    if (kind === 'upload') {
      const p = receiptProblem(file)
      setFileProblem(p)
      if (p) return
      if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
        onPhotoRef.current(file)
        return
      }
    }
    setFileProblem(null)
    onPhotoRef.current(await shrinkImage(file))
  }

  const status = !online
    ? { text: OFFLINE }
    : mode === 'qr' && camera === 'unavailable'
      ? { text: 'Camera not available' }
      : message
  const fileInput = (kind: 'photo' | 'upload') => (
    <input type="file" aria-label={kind === 'photo' ? 'Take photo' : 'Upload file'} disabled={!online}
      accept={kind === 'photo' ? 'image/*' : RECEIPT_ACCEPT} capture={kind === 'photo' ? 'environment' : undefined}
      onChange={(e) => {
        const f = e.target.files?.[0]
        e.target.value = ''
        void attach(f, kind)
      }} />
  )

  return (
    <div ref={root} className="scan" role="dialog" aria-modal="true" aria-label="Scan receipt" tabIndex={-1}>
      <div className="scan__view">
        {mode === 'qr' && online && camera === 'ok' && (
          <>
            <video ref={video} className="scan__video" muted playsInline aria-label="Camera" />
            <div className="scan__frame" aria-hidden="true" />
          </>
        )}
        <div className="scan__top">
          <button ref={closeBtn} type="button" className="scan__btn" aria-label="Close" onClick={() => onCloseRef.current()}>
            <CloseIcon />
          </button>
          <h2 className="scan__title">Scan receipt</h2>
          <span className="scan__btn-slot" />
        </div>
        {mode === 'qr' && online && camera === 'ok' && !status && (
          <p className="scan__pill">{looking ? 'Reading the receipt…' : 'Point at the QR on your receipt'}</p>
        )}
        <div className="scan__notes" aria-live="polite">
          {status && (
            <div className="scan__note">
              <p className="scan__note-text">{status.text}</p>
              {'hint' in status && status.hint && <p className="scan__note-hint">{status.hint}</p>}
            </div>
          )}
          {mode === 'photo' && online && (
            <div className="scan__note"><p className="scan__note-text">The photo is attached to the entry. Type the details yourself.</p></div>
          )}
          {fileProblem && <div className="scan__note scan__note--bad" role="alert"><p className="scan__note-text">{fileProblem}</p></div>}
        </div>
      </div>

      <div className="scan__ctrl">
        <div className="scan__seg">
          <Segmented<Mode> label="Scan mode" options={MODES} value={mode}
            onChange={(m) => { setMode(m); setMessage(null) }} />
        </div>
        <div className="scan__row">
          <label className={online ? 'scan__link' : 'scan__link scan__link--off'}>
            {fileInput('upload')}
            Upload file
          </label>
          {mode === 'photo' ? (
            <label className={online ? 'scan__shutter' : 'scan__shutter scan__shutter--off'}>
              {fileInput('photo')}
              <span className="scan__shutter-text">Take photo</span>
            </label>
          ) : <span className="scan__shutter-gap" aria-hidden="true" />}
          <button type="button" className="scan__link scan__link--end" onClick={() => onCloseRef.current()}>Type it instead</button>
        </div>
      </div>
    </div>
  )
}
