/**
 * How a merchant becomes a rule pattern. Mirrors app/services/category_rules.py (`fold`, `normalise_pattern`); both
 * sides are tested against one list of spellings (rule_normalisation_cases.json), so the suggestion, the rule and the
 * composer's pre-selection agree.
 */
export const MIN_PATTERN_LENGTH = 2
export const MAX_PATTERN_LENGTH = 200

/** Case-fold, strip accents, final ς → σ, collapse spaces. */
export function fold(text: string | null | undefined): string {
  if (!text) return ''
  const stripped = text.toLowerCase().normalize('NFD').replace(/\p{M}/gu, '')
  return stripped.replace(/ς/g, 'σ').split(/\s+/).filter(Boolean).join(' ')
}

/** The stored form of a pattern, or null when it is too short to use. */
export function normalisePattern(text: string | null | undefined): string | null {
  const cleaned = fold(text)
  return cleaned.length < MIN_PATTERN_LENGTH ? null : cleaned.slice(0, MAX_PATTERN_LENGTH)
}
