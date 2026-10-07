import { PlusIcon } from '../../../ui/icons'
import { MinusIcon } from './icons'
import { formatQty } from './types'

interface StepperProps {
  /** The item's name: the buttons read "Increase Milk" / "Decrease Milk". */
  name: string
  value: number
  onStep: (delta: 1 | -1) => void
  /** The smallest value − may reach (0). */
  min?: number
  disabled?: boolean
  size?: 'md' | 'lg'
  /** What the number counts, for the group's name ("Milk in stock"). */
  label?: string
}

/** − n +, 44 px targets; the value is announced when it changes. */
export function Stepper({ name, value, onStep, min = 0, disabled = false, size = 'md', label }: StepperProps) {
  return (
    <div className={`pantry-step${size === 'lg' ? ' pantry-step--lg' : ''}`} role="group" aria-label={label ?? `${name} in stock`}>
      <button type="button" className="pantry-step__btn" aria-label={`Decrease ${name}`}
        disabled={disabled || value <= min} onClick={() => onStep(-1)}>
        <MinusIcon />
      </button>
      <span className="pantry-step__n ui-num" data-testid="pantry-qty" aria-live="polite">{formatQty(value)}</span>
      <button type="button" className="pantry-step__btn" aria-label={`Increase ${name}`}
        disabled={disabled} onClick={() => onStep(1)}>
        <PlusIcon />
      </button>
    </div>
  )
}
