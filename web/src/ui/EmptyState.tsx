import type { ReactNode } from 'react'
import { Link } from 'react-router'

export interface EmptyStateProps {
  title: string
  body?: string
  icon?: ReactNode
  action?: { label: string; to?: string; onClick?: () => void }
}

export function EmptyState({ title, body, icon, action }: EmptyStateProps) {
  return (
    <div className="ui-empty">
      {icon}
      <p className="ui-empty__title">{title}</p>
      {body && <p className="ui-empty__body">{body}</p>}
      {action &&
        (action.to ? (
          <Link className="btn btn--primary" to={action.to}>{action.label}</Link>
        ) : (
          <button type="button" className="btn" onClick={action.onClick}>{action.label}</button>
        ))}
    </div>
  )
}
