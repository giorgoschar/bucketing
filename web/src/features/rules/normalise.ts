/**
 * How a merchant becomes a rule pattern. Mirrors app/services/category_rules.py (`fold`, `normalise_pattern`); both
 * sides are tested against one list of spellings (rule_normalisation_cases.json), so the suggestion, the rule and the
 * composer's pre-selection agree.
 */
export const MIN_PATTERN_LENGTH = 2
export const MAX_PATTERN_LENGTH = 200

// Python's str.split() whitespace (not JS \s: that has U+FEFF and lacks U+0085 and U+001C-1F).
const SPACE = /[\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+/
// The server drops combining characters with a non-zero combining class. Every one of these has one (U+034F does not).
const STRIP = /[\u0300-\u034e\u0350-\u036f]/g

/**
 * Case-fold, strip accents, final ς → σ, collapse spaces, as the server's `fold` does. Python's `casefold()` has no
 * JS twin; upper-then-lower gives the same result for ß, ﬁ, µ, ᾈ and the rest of the full case foldings that matter.
 */
export function fold(text: string | null | undefined): string {
  if (!text) return ''
  const folded = text.toUpperCase().toLowerCase().normalize('NFD').replace(STRIP, '')
  return folded.replace(/ς/g, 'σ').split(SPACE).filter(Boolean).join(' ')
}

/**
 * false when the text still holds a mark whose combining class this file cannot know (Thai, Arabic, Hebrew, ...): the
 * server would strip some of them, the device does not, so the two could disagree. Such text is never matched on the
 * device (fail safe: no pre-selection, the server still applies the rule). Variation selectors are kept by both.
 */
export const isFoldSafe = (text: string | null | undefined): boolean => !/[^\uFE00-\uFE0F\P{M}]/u.test(fold(text))

/** The stored form of a pattern, or null when it is too short to use. */
export function normalisePattern(text: string | null | undefined): string | null {
  const cleaned = fold(text)
  return cleaned.length < MIN_PATTERN_LENGTH ? null : cleaned.slice(0, MAX_PATTERN_LENGTH)
}
