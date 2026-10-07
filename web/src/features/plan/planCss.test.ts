// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const css = readFileSync(new URL('./plan.css', import.meta.url), 'utf8')
const kit = readFileSync(new URL('../../ui/ui.css', import.meta.url), 'utf8')
const shell = readFileSync(new URL('../../shell/shell.css', import.meta.url), 'utf8')

const px = (block: string | undefined, prop: string): number => {
  const m = new RegExp(`${prop}:\\s*([\\d.]+)px`).exec(block ?? '')
  if (!m) throw new Error(`no ${prop} in ${block}`)
  return Number(m[1])
}
const horizontalPadding = (block: string | undefined): number => {
  const m = /padding:\s*([\d.]+)(?:px)?\s+([\d.]+)px/.exec(block ?? '')
  if (!m) throw new Error(`no padding in ${block}`)
  return Number(m[2])
}

// Pantry spec §4.1: five segments fit one row at 390 px without scrolling or truncating a label.
it('the five Plan segments fit on one row at 390 px', () => {
  const seg = /\.plan__seg \.ui-seg\s*\{([^}]*)\}/.exec(css)?.[1]
  expect(seg).toMatch(/flex-wrap:\s*nowrap/)
  const opt = /\.plan__seg \.ui-seg__opt\s*\{([^}]*)\}/.exec(css)?.[1]
  expect(opt).not.toMatch(/text-overflow|overflow:\s*hidden/)
  const font = px(opt, 'font-size')
  const pad = horizontalPadding(opt)
  const screenPad = horizontalPadding(/\.screen\s*\{([^}]*)\}/.exec(shell)?.[1])
  const kitSeg = /\.ui-seg\s*\{([^}]*)\}/.exec(kit)?.[1]
  const segPad = px(kitSeg, 'padding')
  const gap = px(kitSeg, 'gap')
  // A generous 0.66 em per character for the 650-weight UI face (its real average is about 0.58 em).
  const labels = ['Upcoming', 'Month', 'Budgets', 'Cash', 'Pantry']
  const text = labels.join('').length * 0.66 * font
  const needed = text + labels.length * 2 * pad + (labels.length - 1) * gap + 2 * segPad
  expect(needed).toBeLessThanOrEqual(390 - 2 * screenPad)
})
