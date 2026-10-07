/** Messages the /app/ worker posts to open pages (src/sw.ts). A notification tap on an open app
 *  window becomes a router navigation, so the app does not reload. */
export interface SwNavigate { type: 'navigate'; url: string }

/** "/app/plan" → "/plan" (the router's basename is /app); null for anything else. Same-origin
 *  paths under /app/ only: a message can never send the app elsewhere. */
export function routerPathFromSwMessage(data: unknown): string | null {
  if (typeof data !== 'object' || data === null) return null
  const { type, url } = data as Partial<SwNavigate>
  if (type !== 'navigate' || typeof url !== 'string' || !url.startsWith('/app/') || url.startsWith('//')) return null
  return url.slice('/app'.length) || '/'
}

/** Listens on the ServiceWorkerContainer; returns the unsubscribe. */
export function listenForSwNavigation(container: EventTarget, navigate: (path: string) => void): () => void {
  const onMessage = (e: Event) => {
    const path = routerPathFromSwMessage((e as MessageEvent).data)
    if (path) navigate(path)
  }
  container.addEventListener('message', onMessage)
  // addEventListener alone does not start a ServiceWorkerContainer's message queue before DOMContentLoaded.
  ;(container as Partial<ServiceWorkerContainer>).startMessages?.()
  return () => container.removeEventListener('message', onMessage)
}
