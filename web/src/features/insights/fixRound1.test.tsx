// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8')

// Finding 1: BillsCard is in the main chunk; the stylesheet must travel with the component that owns the classes.
it('BillRowLink imports the stylesheet that styles .billrow and .billscard__list', () => {
  expect(read('./bills/BillRowLink.tsx')).toMatch(/import ['"]\.\/bills\.css['"]/)
  expect(read('./widgets/cards.tsx')).toMatch(/BillRowLink/)
})
