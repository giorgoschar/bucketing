import { useRouteError } from 'react-router'

/** A screen's route errorElement (P3 final review M2). It renders inside the shell's Outlet, so the tab bar
 *  stays. The usual cause is a lazy chunk that 404s after a deploy; a reload fetches the new one. */
export function ScreenError() {
  const error = useRouteError()
  console.error(error)
  return (
    <section className="screen screen-error" role="alert">
      <p className="screen-error__title">This screen didn’t load</p>
      <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>Reload</button>
    </section>
  )
}
