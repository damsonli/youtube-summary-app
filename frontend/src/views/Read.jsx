import { useEffect, useRef, useState } from 'react'
import { api, isChannelUrl, storage, streamAnalyze } from '../api.js'
import Article from '../components/Article.jsx'

const PROVIDER_NAMES = { ollama: 'Ollama (local)', openai: 'OpenAI', claude: 'Claude' }

export default function Read() {
  const [url, setUrl] = useState('')
  const [limit, setLimit] = useState(5)
  const [providers, setProviders] = useState([])
  const [provider, setProvider] = useState(storage.get('provider'))
  const [progress, setProgress] = useState(null)
  const [items, setItems] = useState([])
  const [problems, setProblems] = useState([])
  const [error, setError] = useState('')
  const abortRef = useRef(null)
  const channel = isChannelUrl(url)
  const busy = progress !== null

  useEffect(() => {
    api.llm().then(({ default: def, providers }) => {
      setProviders(providers)
      setProvider((p) => (providers.some((x) => x.name === p && x.configured) ? p : def))
    }).catch((e) => setError(`Could not load AI providers: ${e.message}`))
    return () => abortRef.current?.abort()
  }, [])

  async function submit(e) {
    e.preventDefault()
    if (!url.trim() || busy) return
    setError('')
    setItems([])
    setProblems([])
    setProgress({ message: channel ? 'Reading the channel' : 'Fetching the video', step: 0, total: 1 })
    storage.set('provider', provider)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await streamAnalyze({ url: url.trim(), provider, limit }, (ev) => {
        if (ev.type === 'progress') setProgress(ev)
        else if (ev.type === 'result') setItems((xs) => [...xs, ev.item])
        else if (ev.type === 'item_error') setProblems((xs) => [...xs, ev])
        else if (ev.type === 'error') setError(ev.message)
      }, ctrl.signal)
    } catch (err) {
      if (err.name !== 'AbortError') setError(err.message)
    } finally {
      setProgress(null)
    }
  }

  const pct = progress?.total ? Math.round((progress.step / progress.total) * 100) : 0
  const usable = providers.filter((p) => p.configured)

  return (
    <div>
      <form onSubmit={submit} className="max-w-3xl">
        <label htmlFor="url" className="block font-serif text-[2.25rem] leading-[1.1] sm:text-[3rem]">
          What should we read?
        </label>
        <p className="mt-3 max-w-[56ch] text-ink-soft">
          Paste a video link for one summary, or a channel link to summarize its latest uploads.
        </p>
        <div className="mt-7 flex flex-col gap-3 sm:flex-row">
          <input
            id="url"
            type="url"
            inputMode="url"
            required
            autoComplete="off"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=…"
            className="field font-serif text-lg sm:text-xl"
          />
          <button type="submit" className="btn shrink-0 justify-center px-6" disabled={busy || !usable.length}>
            {busy ? 'Summarizing…' : channel ? 'Summarize channel' : 'Summarize'}
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-3 text-sm text-ink-soft">
          {usable.length > 0 && (
            <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <legend className="sr-only">AI provider</legend>
              {usable.map((p) => (
                <label key={p.name} className="flex cursor-pointer items-center gap-1.5">
                  <input
                    type="radio"
                    name="provider"
                    value={p.name}
                    checked={provider === p.name}
                    onChange={() => setProvider(p.name)}
                    className="accent-[var(--ink)]"
                  />
                  <span className={provider === p.name ? 'text-ink' : ''}>{PROVIDER_NAMES[p.name]}</span>
                  {p.status === 'error' && <span className="text-danger" title={p.detail}>(unreachable)</span>}
                </label>
              ))}
            </fieldset>
          )}
          {channel && (
            <label className="flex items-center gap-2">
              Latest
              <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="field w-auto py-1">
                {[3, 5, 10, 15].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              videos
            </label>
          )}
        </div>
        {providers.length > 0 && !usable.length && (
          <p className="mt-4 text-danger">
            No AI provider is set up yet. <a href="#/settings">Set one up in Settings</a>.
          </p>
        )}
      </form>

      <div aria-live="polite" className="mt-10 max-w-3xl">
        {busy && (
          <div className="text-sm text-ink-soft">
            <p className="pulse">{progress.message}</p>
            <div className="mt-2 h-[3px] w-full overflow-hidden rounded bg-rule" aria-hidden="true">
              <div className="h-full bg-ink transition-[width] duration-500" style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}
        {error && <p className="text-danger" role="alert">{error}</p>}
        {problems.map((p) => (
          <p key={p.url} className="mt-2 text-sm text-danger">
            Skipped <a href={p.url} target="_blank" rel="noreferrer">{p.url}</a>: {p.message}
          </p>
        ))}
      </div>

      {items.length > 0 && (
        <div className="mt-6 space-y-14">
          {items.map((v) => <Article key={v.id} video={v} />)}
        </div>
      )}
    </div>
  )
}
