export default function App() {
  return (
    <main style={{ padding: 'max(24px, env(safe-area-inset-top)) 16px 24px' }}>
      <p style={{ color: 'var(--muted)', fontSize: 12, letterSpacing: '.08em', textTransform: 'uppercase', fontWeight: 600 }}>
        Tameio · scaffold
      </p>
      <h1 style={{ fontFamily: 'var(--font-display)', fontWeight: 600, letterSpacing: '-.02em', margin: '8px 0' }}>
        New app in progress
      </h1>
      <p style={{ color: 'var(--ink-2)', maxWidth: '60ch' }}>
        The current app keeps running at the site root. This build is served under /app until cutover.
      </p>
    </main>
  )
}
