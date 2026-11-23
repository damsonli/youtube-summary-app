import { useEffect, useState } from 'react'
import Read from './views/Read.jsx'
import Download from './views/Download.jsx'
import Library from './views/Library.jsx'
import Channels from './views/Channels.jsx'
import Settings from './views/Settings.jsx'

const BRAND = 'Tube Desk'

const ROUTES = [
  { id: 'summarize', label: 'Summarize', View: Read },
  { id: 'download', label: 'Download', View: Download },
  { id: 'library', label: 'Library', View: Library },
  { id: 'channels', label: 'Channels', View: Channels },
  { id: 'settings', label: 'Settings', View: Settings },
]

// Older links (including ones in sent emails) keep working.
const ALIASES = { read: 'summarize', subscriptions: 'channels', status: 'settings' }

/** "#/download?url=…" -> { route, params: { url } } */
function currentLocation() {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const [path, query = ''] = raw.split('?')
  const id = ALIASES[path] ?? path
  return {
    route: ROUTES.find((r) => r.id === id) ?? ROUTES[0],
    params: Object.fromEntries(new URLSearchParams(query)),
  }
}

export default function App() {
  const [loc, setLoc] = useState(currentLocation)

  useEffect(() => {
    const onHash = () => {
      setLoc(currentLocation())
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    document.title = `${loc.route.label} · ${BRAND}`
  }, [loc.route])

  const { route, params } = loc
  const { View } = route
  return (
    <div className="mx-auto max-w-5xl px-4 sm:px-8">
      <header className="flex flex-wrap items-center justify-between gap-x-8 gap-y-3 border-b border-rule py-5">
        <a href="#/summarize" className="inline-flex items-center gap-2 text-xl font-semibold tracking-tight text-ink no-underline">
          <svg className="logo-mark" viewBox="0 0 24 24" width="26" height="26" aria-hidden="true">
            <rect width="24" height="24" rx="6" className="logo-mark-tile" />
            <rect x="6" y="6.5" width="12" height="2.2" rx="1.1" className="logo-mark-line" />
            <rect x="6" y="10.9" width="8.5" height="2.2" rx="1.1" className="logo-mark-line" />
            <rect x="6" y="15.3" width="5.5" height="2.2" rx="1.1" className="logo-mark-bar" />
          </svg>
          {BRAND}
        </a>
        <nav aria-label="Main">
          <ul className="flex flex-wrap gap-2 text-[0.9375rem]">
            {ROUTES.map((r) => (
              <li key={r.id}>
                <a
                  href={`#/${r.id}`}
                  aria-current={r.id === route.id ? 'page' : undefined}
                  className="chip"
                >
                  {r.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main className="py-10 sm:py-14">
        {/* Remount when the link's URL changes so a prefilled form starts fresh. */}
        <View key={`${route.id}|${params.url ?? ''}`} params={params} />
      </main>
    </div>
  )
}

