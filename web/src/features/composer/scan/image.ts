export const MAX_SIDE = 2000
export const JPEG_QUALITY = 0.85

export function fitWithin(w: number, h: number, max = MAX_SIDE): { w: number; h: number } {
  const scale = Math.min(1, max / Math.max(w, h))
  return { w: Math.round(w * scale), h: Math.round(h * scale) }
}

export const jpegName = (name: string): string => `${name.replace(/\.[^.]*$/, '') || 'receipt'}.jpg`

/** Shrinks a receipt photo for upload (spec §4.7). Never reads anything from the image. */
export async function shrinkImage(file: File): Promise<File> {
  if (typeof createImageBitmap !== 'function') return file
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    const { w, h } = fitWithin(bitmap.width, bitmap.height)
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      bitmap.close()
      return file
    }
    ctx.drawImage(bitmap, 0, 0, w, h)
    bitmap.close()
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY))
    return blob ? new File([blob], jpegName(file.name), { type: 'image/jpeg' }) : file
  } catch {
    return file // e.g. HEIC where the browser cannot decode it: upload it as it is
  }
}
