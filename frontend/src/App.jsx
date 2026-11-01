import { useEffect, useState } from 'react'
import Read from './views/Read.jsx'
import Library from './views/Library.jsx'
import Channels from './views/Channels.jsx'
import Settings from './views/Settings.jsx'

const ROUTES = [
  { id: 'read', label: 'Read', View: Read },
  { id: 'library', label: 'Library', View: Library },
  { id: 'channels', label: 'Channels', View: Channels },
  { id: 'settings', label: 'Settings', View: Settings },
]

// Older links (including ones in sent emails) keep working.
const ALIASES = { subscriptions: 'channels', status: 'settings' }

function currentRoute() {
  const raw = window.location.hash.replace(/^#\/?/, '')
  const id = ALIASES[raw] ?? raw
  return ROUTES.find((r) => r.id === id) ?? ROUTES[0]
}

export default function App() {
  const [route, setRoute] = useState(currentRoute)

  useEffect(() => {
    const onHash = () => {
      setRoute(currentRoute())
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const { View } = route
  return (
    <div className="mx-auto max-w-5xl px-4 sm:px-8">
      <header className="flex flex-wrap items-baseline justify-between gap-x-8 gap-y-3 border-b border-rule py-6">
        <a href="#/read" className="font-serif text-[1.75rem] leading-none text-ink no-underline italic">
          Digest
        </a>
        <nav aria-label="Main">
          <ul className="flex flex-wrap gap-x-6 gap-y-1 text-[0.9375rem]">
            {ROUTES.map((r) => (
              <li key={r.id}>
                <a
                  href={`#/${r.id}`}
                  aria-current={r.id === route.id ? 'page' : undefined}
                  className={
                    r.id === route.id
                      ? 'marker font-semibold no-underline'
                      : 'text-ink-soft no-underline hover:text-ink'
                  }
                >
                  {r.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main className="py-10 sm:py-14">
        <View />
      </main>
    </div>
  )
}
