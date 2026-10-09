// @vitest-environment node
/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

// The 2c Chip kit (Activity's quick filters, Pantry's "Show" chips). Until the polish round, controls.css's
// picker rules shared its class names and, coming later in the bundle, decided how these chips looked in
// production: 44 px tall, 14 px text, pressed in ink, the row flush with the screen edge. When the picker got
// its own classes those values had to move here, or the chips would have changed (32 px, 13 px, accent,
// inset). This pins the production look; changing it is a design decision, not a side effect.
const css = readFileSync(new URL('./ui-2c.css', import.meta.url), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

/** The winning declarations of every rule whose selector list has exactly `sel` (later rules win). */
function decls(sel: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [, head, body] of css.matchAll(/([^{}@]+)\{([^{}]*)\}/g)) {
    if (!head.split(',').map((s) => s.trim()).includes(sel)) continue
    for (const d of body.split(';')) {
      const i = d.indexOf(':')
      if (i > 0) out[d.slice(0, i).trim()] = d.slice(i + 1).trim()
    }
  }
  return out
}

describe('the 2c chips keep their production look', () => {
  it('the row: flush with the screen edge, 2 px block padding (a 48 px row)', () => {
    const row = decls('.chips')
    expect(row).toMatchObject({
      display: 'flex', gap: '8px', 'overflow-x': 'auto', 'margin-inline': '-16px', 'margin-block': '-6px',
      'padding-inline': '0', 'padding-block': '2px',
    })
  })

  it('a chip: 44 px tall, 14 px padding, 600 14px/1 body text', () => {
    const chip = decls('.chip')
    expect(chip).toMatchObject({
      'min-height': '44px', padding: '0 14px', font: '600 14px/1 var(--font-body)', position: 'relative',
      display: 'inline-flex', 'align-items': 'center', gap: '6px', 'white-space': 'nowrap',
      background: 'var(--surface)', border: '1px solid var(--line)', color: 'var(--ink-2)',
      'border-radius': 'var(--r-pill)',
    })
    expect(chip['font-size']).toBeUndefined()
    expect(chip['font-weight']).toBeUndefined()
  })

  it('pressed is ink on the page colour, not the accent', () => {
    expect(decls('.chip.on')).toEqual({ background: 'var(--ink)', color: 'var(--bg)', 'border-color': 'var(--ink)' })
  })

  it('keeps the focus ring, the press feedback and its reduced-motion off switch', () => {
    expect(decls('.chip:focus-visible')).toMatchObject({ outline: '2px solid var(--accent)', 'outline-offset': '2px' })
    expect(css).toMatch(/\.chip:active\s*\{\s*transform:\s*scale\(\.97\)/)
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{[^}]*\.chip:active\s*\{\s*transform:\s*none/)
  })
})
