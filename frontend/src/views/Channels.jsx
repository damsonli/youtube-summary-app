import { useEffect, useState } from 'react'
import { api, storage } from '../api.js'
import { Notice, PageHeader } from '../components/ui.jsx'
import { clock, listJoin, prettyZone, timeAgo, when } from '../format.js'

function Step({ n, title, done, children }) {
  return (
    <li className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-3 border-t border-rule pt-6 pb-8 sm:grid-cols-[3rem_minmax(0,1fr)]">
      <span
        aria-hidden="true"
        className={`font-serif text-[1.75rem] leading-none ${done ? 'text-ink-faint' : 'text-ink'}`}
      >
        {n}
      </span>
      <div className="min-w-0">
        <h2 className="font-serif text-[1.5rem] leading-tight">{title}</h2>
        <div className="mt-4">{children}</div>
      </div>
    </li>
  )
}

export default function Channels() {
  const [status, setStatus] = useState(null)
  const [email, setEmail] = useState(storage.get('email'))
  const [draftEmail, setDraftEmail] = useState(storage.get('email'))
  const [editingEmail, setEditingEmail] = useState(!storage.get('email'))
  const [subs, setSubs] = useState(null)
  const [url, setUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const [confirming, setConfirming] = useState(null)
  const [note, setNote] = useState(null)
  const [checkNote, setCheckNote] = useState(null)

  useEffect(() => {
    api.status().then(setStatus, () => {})
  }, [])

  useEffect(() => {
    if (!email) return
    api.subscriptions(email).then(setSubs, (e) => setNote({ error: true, text: e.message }))
  }, [email])

  const reload = () => api.subscriptions(email).then(setSubs, (e) => setNote({ error: true, text: e.message }))

  function saveAddress(e) {
    e.preventDefault()
    const addr = draftEmail.trim()
    if (!addr) return
    storage.set('email', addr)
    setEmail(addr)
    setEditingEmail(false)
    setNote(null)
  }

  async function follow(e) {
    e.preventDefault()
    setAdding(true)
    setNote(null)
    try {
      const sub = await api.subscribe({ channel_url: url.trim(), email })
      setUrl('')
      setNote({ text: `Following ${sub.channel_name}. Its next new video will be in your email.` })
      reload()
    } catch (err) {
      setNote({ error: true, text: err.message })
    } finally {
      setAdding(false)
    }
  }

  async function unfollow(sub) {
    try {
      await api.unsubscribe(sub.id)
      setSubs((xs) => xs.filter((x) => x.id !== sub.id))
      setNote({ text: `Unfollowed ${sub.channel_name}.` })
    } catch (err) {
      setNote({ error: true, text: err.message })
    } finally {
      setConfirming(null)
    }
  }

  async function checkNow() {
    try {
      await api.runCheck()
      setCheckNote({ text: 'Checking all channels now. If anything is new, the email arrives in a minute or two.' })
    } catch (err) {
      setCheckNote({ error: true, text: err.message })
    }
  }

  const times = status?.schedule_times?.map(clock) ?? []
  const count = subs?.length ?? 0

  return (
    <div className="max-w-3xl">
      <PageHeader title="Channels">
        Follow YouTube channels and get one email with their new videos
        {status?.next_runs?.length ? (
          <>, every day at {listJoin(times)} ({prettyZone(status.timezone)}).</>
        ) : (
          <>. Automatic checks are off right now, so emails only go out when you check by hand.</>
        )}{' '}
        Each email lists every new video, and the newest ones come with an AI summary.
      </PageHeader>

      <ol>
        <Step n="1" title="Where should the email go?" done={!editingEmail}>
          {editingEmail ? (
            <form onSubmit={saveAddress} className="flex flex-col gap-3 sm:flex-row">
              <label className="sr-only" htmlFor="email">Email address</label>
              <input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={draftEmail}
                onChange={(e) => setDraftEmail(e.target.value)}
                placeholder="you@example.com"
                className="field"
              />
              <button type="submit" className="btn shrink-0 justify-center">Use this address</button>
            </form>
          ) : (
            <p>
              Sending to <span className="font-semibold">{email}</span>.{' '}
              <button type="button" className="btn-text underline" onClick={() => setEditingEmail(true)}>
                Change
              </button>
            </p>
          )}
          <p className="mt-2 text-sm text-ink-faint">
            Each address has its own list of channels, so several people can use this app.
          </p>
        </Step>

        <Step n="2" title="Add a channel">
          {!email ? (
            <p className="text-ink-soft">Enter your email address first.</p>
          ) : (
            <form onSubmit={follow}>
              <label htmlFor="channel" className="block text-sm text-ink-soft">
                Open the channel on YouTube and copy the address from your browser, for example
                {' '}<span className="text-ink">youtube.com/@veritasium</span>.
              </label>
              <div className="mt-3 flex flex-col gap-3 sm:flex-row">
                <input
                  id="channel"
                  type="url"
                  required
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://www.youtube.com/@channel"
                  className="field"
                />
                <button type="submit" className="btn shrink-0 justify-center" disabled={adding}>
                  {adding ? 'Following…' : 'Follow channel'}
                </button>
              </div>
              <p className="mt-2 text-sm text-ink-faint">
                Videos already on the channel are skipped; you only get uploads from now on.
              </p>
              <div className="mt-3" aria-live="polite"><Notice note={note} /></div>
            </form>
          )}
        </Step>

        <Step n="3" title={count ? `Channels you follow (${count})` : 'Channels you follow'}>
          {!email && <p className="text-ink-soft">Your channels will appear here.</p>}
          {email && subs?.length === 0 && (
            <p className="text-ink-soft">
              None yet. Add a channel above and its new videos will start arriving at {email}.
            </p>
          )}
          {count > 0 && (
            <ul className="divide-y divide-rule border-y border-rule">
              {subs.map((s) => (
                <li key={s.id} className="py-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
                    <a
                      href={s.channel_url.replace(/\/videos$/, '')}
                      target="_blank"
                      rel="noreferrer"
                      className="font-serif text-xl text-ink no-underline hover:underline"
                    >
                      {s.channel_name}
                    </a>
                    {confirming === s.id ? (
                      <span className="flex items-baseline gap-3 text-sm">
                        Stop emails from this channel?
                        <button type="button" className="btn-text font-semibold text-danger underline" onClick={() => unfollow(s)}>
                          Unfollow
                        </button>
                        <button type="button" className="btn-text underline" onClick={() => setConfirming(null)}>
                          Keep
                        </button>
                      </span>
                    ) : (
                      <button type="button" className="btn-text text-sm" onClick={() => setConfirming(s.id)}>
                        Unfollow
                      </button>
                    )}
                  </div>
                  <p className="mt-0.5 text-sm text-ink-soft">
                    {s.last_checked ? `Checked ${timeAgo(s.last_checked)}` : 'Not checked yet'}
                    {s.created_at && <>, following since {new Date(s.created_at).toLocaleDateString()}</>}
                  </p>
                  {s.last_error && (
                    <p className="mt-1 text-sm text-danger">
                      The last check didn’t finish: {s.last_error}. It will be retried at the next check, and no
                      videos are lost.
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Step>
      </ol>

      {status && (
        <div className="border-t border-rule pt-6 text-sm text-ink-soft">
          <p>
            {status.next_runs?.[0]
              ? <>Next check: <span className="text-ink">{when(status.next_runs[0])}</span>.</>
              : 'Automatic checks are turned off.'}{' '}
            Times and AI options are on the <a href="#/settings">Settings</a> page.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-4">
            <button type="button" className="btn btn-quiet" onClick={checkNow}>Check for new videos now</button>
            <Notice note={checkNote} />
          </div>
        </div>
      )}
    </div>
  )
}
