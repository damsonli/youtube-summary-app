import { useCallback, useEffect, useState } from 'react'
import { api, storage } from '../api.js'
import { Field, Notice, PageHeader, Section } from '../components/ui.jsx'
import { clock, prettyZone, when } from '../format.js'

const NUMERIC = new Set(['ollama_num_ctx', 'transcript_max_chars', 'max_ai_summaries_per_channel', 'smtp_port'])
const AI_KEYS = ['llm_service', 'ollama_host', 'ollama_model', 'ollama_num_ctx', 'openai_base_url', 'openai_model',
  'anthropic_base_url', 'claude_model', 'claude_effort']
const DIGEST_KEYS = ['schedule_times', 'timezone', 'max_ai_summaries_per_channel', 'transcript_max_chars']
const SMTP_KEYS = ['smtp_server', 'smtp_port', 'smtp_security', 'email_user', 'from_email', 'app_url']

const RUN_STATUS = {
  ok: 'Finished', partial: 'Finished with errors', error: 'Failed', running: 'Running',
  interrupted: 'Interrupted by a restart', skipped: 'Skipped',
}

const norm = (v) => (v === null || v === undefined ? '' : String(v))
const pick = (obj, keys) => Object.fromEntries(keys.map((k) => [k, norm(obj[k])]))

/**
 * One form for a group of settings. The parent remounts it (via `key`) after saving,
 * so the draft always starts from the saved values.
 */
function SettingsForm({ settings, keys, onSaved, saved, children }) {
  const [draft, setDraft] = useState(() => pick(settings.values, keys))
  const [errors, setErrors] = useState({})
  const [note, setNote] = useState(saved ? { text: 'Saved. Changes apply right away.' } : null)
  const [busy, setBusy] = useState(false)
  const changed = keys.filter((k) => draft[k] !== norm(settings.values[k]))

  async function send(changes) {
    setBusy(true)
    setErrors({})
    setNote(null)
    try {
      onSaved(await api.saveSettings(changes))
    } catch (err) {
      setErrors(err.fields ?? {})
      setNote({ error: true, text: err.message })
    } finally {
      setBusy(false)
    }
  }

  function save(e) {
    e.preventDefault()
    send(Object.fromEntries(changed.map((k) => [k, NUMERIC.has(k) ? Number(draft[k]) : draft[k]])))
  }

  const set = (k) => (e) => {
    const v = e?.target ? e.target.value : e
    setDraft((d) => ({ ...d, [k]: v }))
  }
  const meta = (k) => ({ source: settings.source[k], error: errors[k], onReset: () => send({ [k]: null }) })

  return (
    <form onSubmit={save} noValidate>
      {children({ draft, set, meta })}
      <div className="mt-6 flex flex-wrap items-center gap-4">
        <button type="submit" className="btn" disabled={busy || changed.length === 0}>
          {busy ? 'Saving…' : 'Save changes'}
        </button>
        {changed.length > 0 && !busy && (
          <button type="button" className="btn-text text-sm underline" onClick={() => setDraft(pick(settings.values, keys))}>
            Discard
          </button>
        )}
        <Notice note={note} />
      </div>
    </form>
  )
}

function ProviderStatus({ info }) {
  if (!info) return <p className="pulse text-sm text-ink-faint">Checking connection…</p>
  if (info.status === 'ok') {
    return <p className="text-sm text-ok">Connected{info.detail ? `. ${info.detail}` : ''}</p>
  }
  if (info.status === 'error') return <p className="text-sm text-danger">{info.detail}</p>
  return <p className="text-sm text-ink-faint">Not set up</p>
}

function TestButton({ body }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  async function run() {
    setBusy(true)
    setResult(null)
    try {
      const r = await api.testProvider(body)
      setResult(r.status === 'ok'
        ? { text: `Works${r.detail ? `. ${r.detail}` : ''}` }
        : { error: true, text: r.status === 'not_configured' ? 'Not set up: add the API key to .env' : r.detail })
    } catch (err) {
      setResult({ error: true, text: err.message })
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <button type="button" className="btn btn-quiet py-1.5 text-sm" onClick={run} disabled={busy}>
        {busy ? 'Testing…' : 'Test connection'}
      </button>
      <Notice note={result} />
    </div>
  )
}

function KeyLine({ set, envName, optional }) {
  return (
    <p className="text-sm text-ink-soft">
      API key: {set ? <span className="text-ok">set in .env ({envName})</span> : (
        <>
          <span className={optional ? '' : 'text-danger'}>not set.</span>{' '}
          {optional ? `Most local servers don't need one; hosted services do (add ${envName} to .env).` : `Add ${envName} to .env and restart.`}
        </>
      )}
    </p>
  )
}

function ProviderBlock({ title, children }) {
  return (
    <fieldset className="mt-6 rounded-md border border-rule p-4 sm:p-5">
      <legend className="px-1 font-serif text-lg">{title}</legend>
      <div className="space-y-4">{children}</div>
    </fieldset>
  )
}

function TimesEditor({ value, onChange }) {
  const times = value ? value.split(',').filter(Boolean) : []
  const update = (list) => onChange(list.filter(Boolean).join(','))
  return (
    <div className="flex flex-wrap items-center gap-2">
      {times.map((t, i) => (
        <span key={i} className="flex items-center gap-1">
          <input
            type="time"
            value={t}
            aria-label={`Check time ${i + 1}`}
            onChange={(e) => update(times.map((x, j) => (j === i ? e.target.value : x)))}
            className="field w-auto py-1.5"
          />
          {times.length > 1 && (
            <button type="button" className="btn-text px-1 text-sm" aria-label={`Remove ${t}`} onClick={() => update(times.filter((_, j) => j !== i))}>
              Remove
            </button>
          )}
        </span>
      ))}
      <button type="button" className="btn-text text-sm underline" onClick={() => update([...times, '18:00'])}>
        Add a time
      </button>
    </div>
  )
}

function timezones(current) {
  let zones
  try {
    zones = Intl.supportedValuesOf('timeZone')
  } catch {
    zones = []
  }
  return [...new Set(['UTC', current, ...zones])].filter(Boolean)
}

const FIREFOX_LINE = 'FIREFOX_PROFILES=/mnt/c/Users/<you>/AppData/Roaming/Mozilla/Firefox/Profiles'

const COOKIE_SOURCES = [
  {
    value: 'firefox',
    title: 'Read from Firefox automatically',
    summary: 'Nothing to export, and it never goes stale: the app reads your Firefox cookies fresh for each video.',
    fits: 'Choose this if you use Firefox on this computer. One-time setup: one line in .env and a restart.',
  },
  {
    value: 'upload',
    title: 'Upload a cookies.txt',
    summary: 'Works with any browser, including Chrome and Edge. You export a file with a browser extension and upload it here.',
    fits: 'Choose this if you don’t use Firefox. Export a new file when YouTube signs it out (every few weeks).',
  },
]

/** One numbered setup step; turns into a check mark when `done`. */
function Step({ n, done, title, children }) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden="true"
        className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold ${done ? 'bg-[var(--ok)] text-white' : 'bg-raised text-ink-soft'}`}
      >
        {done ? '✓' : n}
      </span>
      <div className="min-w-0 flex-1 space-y-1.5 text-sm leading-relaxed">
        <p className="font-semibold">{title}{done && <span className="sr-only"> (done)</span>}</p>
        {children}
      </div>
    </li>
  )
}

function CopyLine({ text }) {
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    }, () => {})
  }
  return (
    <span className="flex items-stretch gap-2">
      <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-md bg-raised px-3 py-2 font-mono text-xs">{text}</code>
      <button type="button" className="btn btn-quiet shrink-0 px-3 py-1 text-xs" onClick={copy}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </span>
  )
}

function cookieSummary(state) {
  const ff = state.firefox
  if (state.active === 'firefox') {
    return ff.signed_in === false
      ? { tone: 'text-danger', text: `Reading Firefox (profile ${ff.profile}), but it isn’t signed in to YouTube. Sign in to YouTube in Firefox.` }
      : { tone: 'text-ok', text: `Signed in: reading your cookies from Firefox (profile ${ff.profile}).` }
  }
  if (state.active === 'upload') {
    const updated = state.upload.updated_at ? ` (updated ${when(state.upload.updated_at)})` : ''
    const fallback = state.source === 'firefox' ? ' Firefox isn’t set up yet, so the uploaded file is used meanwhile.' : ''
    return { tone: 'text-ok', text: `Signed in with your uploaded cookies.txt${updated}.${fallback}` }
  }
  return { tone: 'text-ink-soft', text: 'Not signed in: the app watches YouTube as a signed-out viewer. Pick a way below.' }
}

/** Take the Firefox sign-in to an instance on another machine, which can't see this Firefox. */
function ExportCookies({ busy, onNote }) {
  const [working, setWorking] = useState(false)

  async function download() {
    setWorking(true)
    onNote(null)
    try {
      await api.exportCookies()
      onNote({ text: 'Downloaded cookies.txt. Upload it on the other server, then delete your copy.' })
    } catch (e) {
      onNote({ error: true, text: e.message })
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-rule p-4 sm:p-5">
      <h3 className="font-semibold">Use this sign-in on another server</h3>
      <p className="text-sm leading-relaxed text-ink-soft">
        If the app also runs on a server that can’t see this Firefox, download your YouTube cookies here as a cookies.txt,
        then on that server open Settings → YouTube sign-in, choose <em>Upload a cookies.txt</em> and upload it.
      </p>
      <button type="button" className="btn btn-quiet" disabled={busy || working} onClick={download}>
        {working ? 'Preparing…' : 'Download cookies.txt'}
      </button>
      <p className="text-sm leading-relaxed text-ink-faint">
        Treat the file like a password: it signs in as you. Only youtube.com cookies are included, not your other Google ones.
        Unlike reading Firefox live, the copy on the server goes stale when YouTube rotates it (every few weeks); download and upload a fresh one then.
      </p>
    </div>
  )
}

function FirefoxSetup({ state, busy, onRefresh }) {
  const ff = state.firefox
  return (
    <div className="space-y-4">
      <ol className="space-y-4">
        <Step n={1} done={ff.signed_in} title="Sign in to YouTube in Firefox">
          <p className="text-ink-soft">On this computer, open youtube.com in Firefox and sign in with the account that has the membership. Firefox can stay open; the app reads a copy of its cookies.</p>
        </Step>
        <Step n={2} done={ff.mounted} title="Tell Docker where Firefox keeps its profiles">
          <p className="text-ink-soft">Add this line to the <code>.env</code> file next to <code>docker-compose.yml</code>, with your Windows user name in place of <code>&lt;you&gt;</code>:</p>
          <CopyLine text={FIREFOX_LINE} />
          <p className="text-ink-faint">
            Not sure of the folder? In Firefox, open <code>about:support</code>, find <em>Profile Folder</em> and click <em>Open Folder</em>; use the folder above it, named <em>Profiles</em>.
            If you run Docker from Windows rather than WSL, write it as <code>C:/Users/&lt;you&gt;/AppData/Roaming/Mozilla/Firefox/Profiles</code>.
            The app gets read-only access.
          </p>
        </Step>
        <Step n={3} done={ff.found} title="Restart the app">
          <p className="text-ink-soft">In the project folder, run:</p>
          <CopyLine text="docker compose up -d" />
          <p className="text-ink-faint">
            {ff.found
              ? `Found Firefox profile “${ff.profile}”${ff.updated_at ? `, last used ${when(ff.updated_at)}` : ''}.`
              : ff.mounted
                ? 'The folder is shared, but there is no Firefox profile in it. Check that it is the Profiles folder.'
                : 'No Firefox folder is shared with the app yet.'}
          </p>
          {ff.error && <p className="text-danger">{ff.error}</p>}
        </Step>
      </ol>
      <button type="button" className="btn btn-quiet" disabled={busy} onClick={onRefresh}>Check again</button>
      <p className="text-sm leading-relaxed text-ink-faint">
        Only Firefox works this way: Chrome and Edge on Windows lock their cookies with encryption.
        The app uses whichever account is signed in to YouTube in Firefox. If Firefox can’t be read, an uploaded cookies.txt is used instead.
      </p>
    </div>
  )
}

function UploadSetup({ state, busy, act, onNote }) {
  const [text, setText] = useState('')

  function pickFile(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (file) file.text().then(setText, () => onNote({ error: true, text: 'Could not read that file' }))
  }

  async function save() {
    if (await act(() => api.saveCookies(text), 'Saved. It is used from the next request on.')) setText('')
  }

  return (
    <div className="space-y-4">
      <ol className="space-y-4">
        <Step n={1} title="Install a cookie exporter">
          <p className="text-ink-soft">In the browser where you’re signed in to YouTube (with the membership), install an extension such as “Get cookies.txt LOCALLY” or Cookie-Editor.</p>
          <p className="text-ink-faint">Tip: export from a private window signed in only to YouTube to keep it apart from your everyday Google login.</p>
        </Step>
        <Step n={2} title="Export the youtube.com cookies">
          <p className="text-ink-soft">On youtube.com, export the cookies in <strong>Netscape / cookies.txt</strong> format.</p>
        </Step>
        <Step n={3} done={state.upload.present} title="Upload or paste the file here">
          <Field label="cookies.txt" help="Treat this like a password: it signs in as you. It is stored in data/ and never shown again.">
            <textarea
              className="field h-28 font-mono text-xs"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="# Netscape HTTP Cookie File"
              spellCheck="false"
              autoComplete="off"
            />
          </Field>
          <div className="flex flex-wrap items-center gap-4 pt-1">
            <label className="btn btn-quiet cursor-pointer">
              Choose file…
              <input type="file" accept=".txt,text/plain" className="sr-only" onChange={pickFile} />
            </label>
            <button type="button" className="btn" disabled={busy || !text.trim()} onClick={save}>
              Save cookies
            </button>
            {state.upload.present && (
              <button type="button" className="btn-text text-sm underline" disabled={busy} onClick={() => act(api.deleteCookies, 'Removed.')}>
                Remove cookies
              </button>
            )}
          </div>
        </Step>
      </ol>
      <p className="text-sm leading-relaxed text-ink-faint">YouTube rotates cookies. If members-only videos start failing again, export and upload a fresh file.</p>
    </div>
  )
}

/** YouTube sign-in: read cookies from Firefox, or paste / upload a cookies.txt. Cookie values are never sent back. */
function CookiesForm({ ffmpeg, onChange }) {
  const [state, setState] = useState(null)
  const [note, setNote] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.cookies().then(setState, (e) => setNote({ error: true, text: e.message }))
  }, [])

  async function act(fn, ok) {
    setBusy(true)
    setNote(null)
    try {
      setState(await fn())
      if (ok) setNote({ text: ok })
      onChange?.()
      return true
    } catch (e) {
      setNote({ error: true, text: e.message })
      return false
    } finally {
      setBusy(false)
    }
  }

  const choose = (source) => act(async () => {
    await api.saveSettings({ cookies_source: source })
    return api.cookies()
  })

  if (state === null) {
    return note ? <Notice note={note} /> : <p className="pulse text-sm text-ink-soft">Checking…</p>
  }
  const summary = cookieSummary(state)
  const firefox = state.source === 'firefox'
  return (
    <div className="space-y-6">
      <p className={`text-sm ${summary.tone}`} role="status">{summary.text}</p>

      <fieldset>
        <legend className="text-sm font-semibold">How should the app get your YouTube cookies?</legend>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          {COOKIE_SOURCES.map((o) => {
            const on = state.source === o.value
            return (
              <label
                key={o.value}
                className={`flex cursor-pointer gap-3 rounded-xl border p-4 transition-colors ${on ? 'border-ink bg-raised' : 'border-rule hover:bg-raised'}`}
              >
                <input
                  type="radio"
                  name="cookies_source"
                  value={o.value}
                  checked={on}
                  disabled={busy}
                  onChange={() => choose(o.value)}
                  className="mt-1 accent-[var(--ink)]"
                />
                <span className="space-y-1.5">
                  <span className="block font-semibold">{o.title}</span>
                  <span className="block text-sm leading-relaxed text-ink-soft">{o.summary}</span>
                  <span className="block text-sm leading-relaxed text-ink-faint">{o.fits}</span>
                </span>
              </label>
            )
          })}
        </div>
      </fieldset>

      <div className="rounded-xl border border-rule p-4 sm:p-5">
        <h3 className="mb-4 font-semibold">{firefox ? 'Set up: read from Firefox' : 'Set up: upload a cookies.txt'}</h3>
        {firefox
          ? <FirefoxSetup state={state} busy={busy} onRefresh={() => act(api.cookies)} />
          : <UploadSetup state={state} busy={busy} act={act} onNote={setNote} />}
      </div>

      {firefox && state.firefox.signed_in && <ExportCookies busy={busy} onNote={setNote} />}

      {firefox && (
        <details className="rounded-xl border border-rule p-4 sm:p-5">
          <summary className="cursor-pointer font-semibold">
            Fallback: upload a cookies.txt{state.upload.present ? ' (one is saved)' : ''}
          </summary>
          <p className="mt-2 text-sm text-ink-faint">Used only while Firefox can’t be read.</p>
          <div className="mt-4">
            <UploadSetup state={state} busy={busy} act={act} onNote={setNote} />
          </div>
        </details>
      )}

      <Notice note={note} />
      {ffmpeg === false && (
        <p className="text-sm text-danger">ffmpeg was not found, so downloads above 720p, MP3 and .srt conversion are unavailable.</p>
      )}
    </div>
  )
}

export default function Settings() {
  const [settings, setSettings] = useState(null)
  const [llm, setLlm] = useState(null)
  const [status, setStatus] = useState(null)
  const [runs, setRuns] = useState([])
  const [savedSection, setSavedSection] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [openRun, setOpenRun] = useState(null)
  const [to, setTo] = useState(storage.get('email'))
  const [mailNote, setMailNote] = useState(null)
  const [checkNote, setCheckNote] = useState(null)

  const refreshActivity = useCallback(
    () => Promise.all([api.status(), api.runs()]).then(([s, r]) => {
      setStatus(s)
      setRuns(r)
    }, () => {}),
    [],
  )

  useEffect(() => {
    api.settings().then(setSettings, (e) => setLoadError(e.message))
    api.llm().then(setLlm, () => setLlm({ providers: [] }))
    Promise.all([api.status(), api.runs()]).then(([s, r]) => {
      setStatus(s)
      setRuns(r)
    }, () => {})
  }, [])

  const running = status?.check_running || runs.some((r) => r.status === 'running')
  useEffect(() => {
    if (!running) return
    const t = setInterval(refreshActivity, 3000)
    return () => clearInterval(t)
  }, [running, refreshActivity])

  const onSaved = (section) => (fresh) => {
    setSettings(fresh)
    setSavedSection(section)
    refreshActivity()
    if (section === 'ai') {
      setLlm(null)
      api.llm().then(setLlm, () => setLlm({ providers: [] }))
    }
  }

  async function runCheck() {
    try {
      await api.runCheck()
      setCheckNote({ text: 'Check started. It shows up in the list below.' })
      refreshActivity()
    } catch (e) {
      setCheckNote({ error: true, text: e.message })
    }
  }

  async function sendTest(e) {
    e.preventDefault()
    setMailNote({ text: 'Sending…' })
    try {
      await api.testEmail(to.trim())
      setMailNote({ text: `Sent to ${to.trim()}. If it isn't in your inbox within a minute, check spam.` })
    } catch (err) {
      setMailNote({ error: true, text: err.message })
    }
  }

  if (loadError) return <p className="text-danger">Could not load settings: {loadError}</p>
  if (!settings) return <p className="pulse text-ink-soft">Loading settings…</p>

  const providerInfo = (name) => llm?.providers.find((p) => p.name === name)
  const formKey = (keys) => keys.map((k) => norm(settings.values[k]) + settings.source[k]).join('|')
  const secrets = settings.secrets_set

  return (
    <div>
      <PageHeader title="Settings">
        Choose which AI writes the summaries, when the daily email goes out and how it’s sent. Changes here apply
        immediately and override the matching value in your <code>.env</code> file. API keys and the email password
        stay in <code>.env</code>.
      </PageHeader>

      <div className="space-y-6">
        <Section
          id="ai"
          title="AI summaries"
          intro="Used for summaries on the Summarize page and in the daily email. You can still pick another one for a single summary on the Summarize page."
        >
          <SettingsForm key={formKey(AI_KEYS)} settings={settings} keys={AI_KEYS} onSaved={onSaved('ai')} saved={savedSection === 'ai'}>
            {({ draft, set, meta }) => (
              <>
                <fieldset>
                  <legend className="text-sm font-semibold">Use by default</legend>
                  <div className="mt-2 flex flex-wrap gap-x-6 gap-y-2">
                    {[['ollama', 'Ollama (local)'], ['openai', 'OpenAI or compatible'], ['claude', 'Claude or compatible']].map(([v, label]) => (
                      <label key={v} className="flex cursor-pointer items-center gap-2">
                        <input type="radio" name="llm_service" value={v} checked={draft.llm_service === v} onChange={set('llm_service')} className="accent-[var(--ink)]" />
                        {label}
                      </label>
                    ))}
                  </div>
                </fieldset>

                <ProviderBlock title="Ollama">
                  <ProviderStatus info={providerInfo('ollama')} />
                  <Field label="Server address" help="Ollama on this computer: http://host.docker.internal:11434. On another machine, use its address." {...meta('ollama_host')}>
                    <input className="field" value={draft.ollama_host} onChange={set('ollama_host')} spellCheck="false" />
                  </Field>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Model" help="Must already be pulled on that server, e.g. llama3.2." {...meta('ollama_model')}>
                      <input className="field" value={draft.ollama_model} onChange={set('ollama_model')} spellCheck="false" />
                    </Field>
                    <Field label="Context size (tokens)" help="How much text the model can read at once. Higher needs more memory." {...meta('ollama_num_ctx')}>
                      <input className="field" type="number" min="2048" step="1024" value={draft.ollama_num_ctx} onChange={set('ollama_num_ctx')} />
                    </Field>
                  </div>
                  <TestButton body={{ provider: 'ollama', host: draft.ollama_host, model: draft.ollama_model }} />
                </ProviderBlock>

                <ProviderBlock title="OpenAI or compatible">
                  <ProviderStatus info={providerInfo('openai')} />
                  <Field
                    label="Server address (optional)"
                    help="Leave empty for OpenAI. For a compatible service, enter its API address: LM Studio http://host.docker.internal:1234/v1, OpenRouter https://openrouter.ai/api/v1, or your vLLM / LiteLLM server."
                    {...meta('openai_base_url')}
                  >
                    <input className="field" value={draft.openai_base_url} onChange={set('openai_base_url')} placeholder="https://api.openai.com/v1" spellCheck="false" />
                  </Field>
                  <Field label="Model" help="The model name as that service spells it, e.g. gpt-4o-mini." {...meta('openai_model')}>
                    <input className="field" value={draft.openai_model} onChange={set('openai_model')} spellCheck="false" />
                  </Field>
                  <KeyLine set={secrets.openai_api_key} envName="OPENAI_API_KEY" optional={Boolean(draft.openai_base_url)} />
                  <TestButton body={{ provider: 'openai', base_url: draft.openai_base_url, model: draft.openai_model }} />
                </ProviderBlock>

                <ProviderBlock title="Claude or compatible">
                  <ProviderStatus info={providerInfo('claude')} />
                  <Field
                    label="Server address (optional)"
                    help="Leave empty for Anthropic’s API. Use this for an Anthropic-compatible gateway or proxy."
                    {...meta('anthropic_base_url')}
                  >
                    <input className="field" value={draft.anthropic_base_url} onChange={set('anthropic_base_url')} placeholder="https://api.anthropic.com" spellCheck="false" />
                  </Field>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Model" help="e.g. claude-haiku-5-5 (fast, cheapest), claude-sonnet-5-5 or claude-opus-5-5." {...meta('claude_model')}>
                      <input className="field" value={draft.claude_model} onChange={set('claude_model')} spellCheck="false" />
                    </Field>
                    <Field label="Effort" help="Higher effort thinks longer: better summaries, slower, more tokens." {...meta('claude_effort')}>
                      <select className="field" value={draft.claude_effort} onChange={set('claude_effort')}>
                        {['low', 'medium', 'high', 'xhigh', 'max'].map((v) => <option key={v} value={v}>{v}</option>)}
                      </select>
                    </Field>
                  </div>
                  <KeyLine set={secrets.anthropic_api_key} envName="ANTHROPIC_API_KEY" optional={Boolean(draft.anthropic_base_url)} />
                  <TestButton body={{ provider: 'claude', base_url: draft.anthropic_base_url, model: draft.claude_model }} />
                </ProviderBlock>
              </>
            )}
          </SettingsForm>
        </Section>

        <Section
          id="digest"
          title="Daily email"
          intro="When channels are checked and what each email contains."
        >
          <SettingsForm key={formKey(DIGEST_KEYS)} settings={settings} keys={DIGEST_KEYS} onSaved={onSaved('digest')} saved={savedSection === 'digest'}>
            {({ draft, set, meta }) => (
              <div className="space-y-5">
                <Field label="Check for new videos at" help="One email per check, only when there’s something new." {...meta('schedule_times')}>
                  <TimesEditor value={draft.schedule_times} onChange={set('schedule_times')} />
                </Field>
                <Field label="Time zone" {...meta('timezone')}>
                  <select className="field" value={draft.timezone} onChange={set('timezone')}>
                    {timezones(draft.timezone).map((z) => <option key={z} value={z}>{prettyZone(z)}</option>)}
                  </select>
                </Field>
                <div className="grid gap-5 sm:grid-cols-2">
                  <Field
                    label="AI summaries per channel"
                    help="Every new video is always listed. This many of the newest per channel also get an AI summary; 0 turns summaries off."
                    {...meta('max_ai_summaries_per_channel')}
                  >
                    <input className="field" type="number" min="0" max="10" value={draft.max_ai_summaries_per_channel} onChange={set('max_ai_summaries_per_channel')} />
                  </Field>
                  <Field
                    label="Transcript length sent to the AI"
                    help="In characters; 20,000 is about 25 minutes of speech. More covers long videos better but costs more, and Ollama needs a larger context size."
                    {...meta('transcript_max_chars')}
                  >
                    <input className="field" type="number" min="1000" max="200000" step="1000" value={draft.transcript_max_chars} onChange={set('transcript_max_chars')} />
                  </Field>
                </div>
              </div>
            )}
          </SettingsForm>
          {status && (
            <p className="mt-4 text-sm text-ink-soft">
              {status.next_runs?.[0]
                ? `Next check: ${when(status.next_runs[0])} (${status.schedule_times.map(clock).join(', ')} ${prettyZone(status.timezone)}).`
                : 'Automatic checks are turned off (SCHEDULER_ENABLED=false).'}
            </p>
          )}
        </Section>

        <Section
          id="email"
          title="Sending email"
          intro="The mail account the digest is sent from. For Gmail, create an App Password and put it in .env as EMAIL_PASSWORD."
        >
          <SettingsForm key={formKey(SMTP_KEYS)} settings={settings} keys={SMTP_KEYS} onSaved={onSaved('email')} saved={savedSection === 'email'}>
            {({ draft, set, meta }) => (
              <div className="space-y-5">
                <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_7rem_10rem]">
                  <Field label="Mail server" {...meta('smtp_server')}>
                    <input className="field" value={draft.smtp_server} onChange={set('smtp_server')} spellCheck="false" />
                  </Field>
                  <Field label="Port" {...meta('smtp_port')}>
                    <input className="field" type="number" value={draft.smtp_port} onChange={set('smtp_port')} />
                  </Field>
                  <Field label="Security" {...meta('smtp_security')}>
                    <select className="field" value={draft.smtp_security} onChange={set('smtp_security')}>
                      <option value="starttls">STARTTLS (587)</option>
                      <option value="ssl">SSL/TLS (465)</option>
                      <option value="none">None</option>
                    </select>
                  </Field>
                </div>
                <div className="grid gap-5 sm:grid-cols-2">
                  <Field label="Username" help="Usually your full email address." {...meta('email_user')}>
                    <input className="field" value={draft.email_user} onChange={set('email_user')} autoComplete="off" spellCheck="false" />
                  </Field>
                  <Field label="Send from" help="Leave empty to use the username." {...meta('from_email')}>
                    <input className="field" value={draft.from_email} onChange={set('from_email')} spellCheck="false" />
                  </Field>
                </div>
                <Field label="Link to this app" help="Used for the “Manage your channels” link at the bottom of each email." {...meta('app_url')}>
                  <input className="field" value={draft.app_url} onChange={set('app_url')} spellCheck="false" />
                </Field>
                <p className="text-sm text-ink-soft">
                  Password:{' '}
                  {secrets.email_password
                    ? <span className="text-ok">set in .env (EMAIL_PASSWORD)</span>
                    : <span className="text-danger">not set. Add EMAIL_PASSWORD to .env and restart.</span>}
                </p>
              </div>
            )}
          </SettingsForm>

          <form onSubmit={sendTest} className="mt-8 border-t border-rule pt-6">
            <Field label="Send a test email to" help="Uses the saved settings above.">
              <span className="flex flex-col gap-3 sm:flex-row">
                <input type="email" required value={to} onChange={(e) => setTo(e.target.value)} className="field" />
                <button type="submit" className="btn btn-quiet shrink-0 justify-center">Send test email</button>
              </span>
            </Field>
            <div className="mt-2"><Notice note={mailNote} /></div>
          </form>
        </Section>

        <Section
          id="signin"
          title="YouTube sign-in"
          intro="Your YouTube cookies let the app open members-only, age-gated and private videos you can watch: for downloads, and for transcripts in summaries and emails."
        >
          <CookiesForm ffmpeg={status?.ffmpeg} onChange={refreshActivity} />
        </Section>

        <Section id="activity" title="Activity" intro="Every check, with what it found and sent. Open one to see its log.">
          <div className="flex flex-wrap items-center gap-4">
            <button type="button" className="btn btn-quiet" onClick={runCheck} disabled={running}>
              {running ? 'Checking…' : 'Check for new videos now'}
            </button>
            <Notice note={checkNote} />
          </div>
          <ol className="mt-5 divide-y divide-rule border-y border-rule text-sm">
            {runs.length === 0 && <li className="py-3 text-ink-soft">No checks have run yet.</li>}
            {runs.map((r) => (
              <li key={r.id} className="py-3">
                <button
                  type="button"
                  className="flex w-full flex-wrap items-baseline justify-between gap-x-4 text-left"
                  aria-expanded={openRun === r.id}
                  onClick={() => setOpenRun(openRun === r.id ? null : r.id)}
                >
                  <span>
                    <span className={r.status === 'error' ? 'text-danger' : r.status === 'running' ? 'pulse' : ''}>
                      {RUN_STATUS[r.status] ?? r.status}
                    </span>
                    <span className="text-ink-soft"> {when(r.started_at)}, {r.trigger === 'manual' ? 'started by hand' : 'scheduled'}</span>
                  </span>
                  <span className="text-ink-soft">
                    {r.videos_found} new video{r.videos_found === 1 ? '' : 's'}, {r.emails_sent} email{r.emails_sent === 1 ? '' : 's'} sent
                  </span>
                </button>
                {openRun === r.id && (
                  <pre className="mt-3 max-h-80 overflow-auto rounded bg-raised p-3 text-xs leading-relaxed whitespace-pre-wrap text-ink-soft">
                    {r.log || 'No log.'}
                  </pre>
                )}
              </li>
            ))}
          </ol>
        </Section>
      </div>
    </div>
  )
}
