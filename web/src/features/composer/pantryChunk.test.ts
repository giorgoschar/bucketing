// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

// The scanner and its decoder must not enter the composer's chunk: the form reaches them only through one lazy import.
it('the composer reaches the camera and the barcode sheet only through the lazy PantryScanFlow', () => {
  const form = readFileSync(new URL('./ComposerForm.tsx', import.meta.url), 'utf8')
  expect(form).toMatch(/lazy\(\(\) => import\('\.\/PantryScanFlow'\)/)
  expect(form).not.toMatch(/from '\.\/PantryScanFlow'/)
  for (const f of ['ComposerForm.tsx', 'Composer.tsx', 'ScanChoiceSheet.tsx', 'MoreSheet.tsx']) {
    const src = readFileSync(new URL(`./${f}`, import.meta.url), 'utf8')
    expect(src).not.toMatch(/from '[^']*(pantry\/scan|BarcodeSheet|pantry\/AddSheet)/)
  }
})
