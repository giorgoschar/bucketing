import { type ReactNode, useId } from 'react'

/** One Insights widget: a section named by its heading, with an optional link or note on the right. */
export function Card({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  const id = useId()
  return (
    <section className="ui-card insights__card" aria-labelledby={id}>
      <div className="insights__cardhead">
        <h2 id={id} className="insights__cardtitle">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}
