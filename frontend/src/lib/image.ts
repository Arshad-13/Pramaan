/** Preparing a photo for upload: phones take 12 MP pictures, but the checker needs about 2800 px. */

export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024
export const MAX_SIDE = 2800
const ACCEPTED = ['image/jpeg', 'image/png', 'image/webp', 'application/pdf']

export function acceptedType(file: File): boolean {
  return ACCEPTED.includes(file.type)
}

/** Shrink a large photo to a JPEG no wider/taller than MAX_SIDE. PDFs and small images pass through. */
export async function prepareUpload(file: File): Promise<File> {
  if (file.type === 'application/pdf') return file
  if (typeof createImageBitmap !== 'function') return file
  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file)
  } catch {
    return file // let the server say it cannot read it
  }
  try {
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height))
    if (scale === 1 && file.size <= MAX_UPLOAD_BYTES) return file
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(bitmap.width * scale)
    canvas.height = Math.round(bitmap.height * scale)
    const context = canvas.getContext('2d')
    if (!context) return file
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.9))
    if (!blob) return file
    return new File([blob], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' })
  } finally {
    bitmap.close()
  }
}
