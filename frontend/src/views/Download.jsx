import { useCallback, useEffect, useRef, useState } from 'react'
import { api, isChannelUrl, saveFile, storage, waitForJob } from '../api.js'
import { Notice, PageHeader, Section } from '../components/ui.jsx'
import QualityPicker from '../components/download/QualityPicker.jsx'
import PlaylistPicker from '../components/download/PlaylistPicker.jsx'
import { JobProgress, Queue } from '../components/download/JobProgress.jsx'
import { codecsFor, estimate, selectionFor } from '../components/download/selection.js'
import { bytes, duration, timeAgo, toolLink } from '../format.js'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function saveAll(files) {
  for (const f of files) {
    saveFile(f.url)
    await sleep(600) // browsers drop rapid back-to-back downloads
  }
}

export default function Download({ params = {} }) {
  const [url, setUrl] = useState(params.url ?? '')
  const [info, setInfo] = useState(null)
  const [loading, setLoading] = useState(Boolean(params.url))
  const [error, setError] = useState('')
  const [status, setStatus] = useState(null)

  const [quality, setQuality] = useState('best')
  const [codec, setCodec] = useState('any')
  const [exactSize, setExactSize] = useState(null)
  const [subLang, setSubLang] = useState('')
  const [withSubs, setWithSubs] = useState(true)
  const [keep, setKeep] = useState(storage.get('download-keep') === '1')

  const [job, setJob] = useState(null)
  const [selected, setSelected] = useState(new Set())
  const [queue, setQueue] = useState(null)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(null)
  const [savedNote, setSavedNote] = useState(null)
  const abortRef = useRef(null)
  const stopRef = useRef(false)

  const loadSaved = useCallback(() => api.savedFiles().then(setSaved, (e) => setSavedNote({ error: true, text: e.message })), [])

  useEffect(() => {
    api.status().then(setStatus, () => {})
    loadSaved()
    return () => abortRef.current?.abort()
  }, [loadSaved])

  // Only state updates after the request returns, so this can also run from an effect.
  const load = useCallback((target) => api.downloadInfo(target).then((j) => {
    setInfo(j)
    setQuality(j.qualities.heights.length ? 'best' : 'a-best')
    setCodec('any')
    const subs = j.subtitles ?? { manual: [], auto: [] }
    const en = subs.manual.find((s) => s.code.startsWith('en')) ?? subs.auto.find((s) => s.code === 'en')
    setSubLang(en?.code ?? '')
    if (j.kind === 'playlist') setSelected(new Set(j.entries.length <= 50 ? j.entries.map((e) => e.id) : []))
  }, (e) => setError(e.message)).finally(() => setLoading(false)), [])

  function fetchInfo(target) {
    if (!target) return
    setError('')
    setInfo(null)
    setJob(null)
    setQueue(null)
    setLoading(true)
    load(target)
  }

  // A link from another page (#/download?url=…) loads right away; `loading` starts true for it.
  useEffect(() => {
    if (params.url) load(params.url)
  }, [params.url, load])

  const sel = info ? selectionFor(quality, codecsFor(info.qualities, quality).includes(codec) ? codec : 'any') : null
  const sizeUrl = info ? (info.kind === 'playlist' ? info.entries[0]?.url : info.url) : null
  const sizeKey = sel && sizeUrl ? JSON.stringify([sizeUrl, sel]) : null

  // Exact size of what yt-dlp would pick (debounced; MP3 size can't be known before converting).
  useEffect(() => {
    if (!sizeKey) return
    const [u, s] = JSON.parse(sizeKey)
    if (s.kind === 'audio' && s.mode === 'mp3') return
    let live = true
    const t = setTimeout(() => {
      api.downloadSize({ url: u, kind: s.kind, height: String(s.height ?? 'best'), codec: s.codec ?? 'any', mode: s.mode ?? '' })
        .then((r) => live && r.bytes && setExactSize({ key: sizeKey, bytes: r.bytes }), () => {})
    }, 350)
    return () => {
      live = false
      clearTimeout(t)
    }
  }, [sizeKey])
  const exactBytes = exactSize?.key === sizeKey ? exactSize.bytes : null

  function setKeepPersist(v) {
    setKeep(v)
    storage.set('download-keep', v ? '1' : '0')
  }

  async function runOne(body) {
    setBusy(true)
    setError('')
    setJob({ status: 'queued', percent: 0, text: 'Starting…' })
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      const started = await api.startDownload({ ...body, keep })
      const final = await waitForJob(started.id, setJob, ctrl.signal)
      if (final.status === 'done') {
        await saveAll(final.files)
        if (keep) loadSaved()
      } else setError(final.error || 'Download failed')
    } catch (e) {
      if (e.name !== 'AbortError') {
        setError(e.message)
        setJob(null)
      }
    } finally {
      setBusy(false)
    }
  }

  function downloadVideo() {
    const subs = sel.kind === 'video' && withSubs && subLang ? subLang : null
    return runOne({ url: info.url, sel, subs, title: info.title })
  }

  function downloadSubsOnly() {
    return runOne({ url: info.url, sel: { kind: 'subs' }, subs: subLang, title: info.title })
  }

  async function downloadPlaylist() {
    const items = info.entries.filter((e) => selected.has(e.id)).map((e) => ({ ...e, state: 'waiting' }))
    if (!items.length) return setError('Select at least one video.')
    setBusy(true)
    setError('')
    setQueue(items)
    stopRef.current = false
    const ctrl = new AbortController()
    abortRef.current = ctrl
    const update = (id, patch) => setQueue((q) => q.map((x) => (x.id === id ? { ...x, ...patch } : x)))
    for (const it of items) {
      if (ctrl.signal.aborted || stopRef.current) break
      update(it.id, { state: 'running', percent: 0 })
      try {
        const started = await api.startDownload({ url: it.url, sel, subs: null, title: it.title, keep })
        const final = await waitForJob(started.id, (j) => update(it.id, { percent: j.percent }), ctrl.signal)
        if (final.status === 'done') {
          await saveAll(final.files)
          update(it.id, { state: 'saved' })
        } else update(it.id, { state: 'error', error: final.error })
      } catch (e) {
        if (e.name === 'AbortError') break
        update(it.id, { state: 'error', error: e.message })
      }
    }
    if (keep) loadSaved()
    setBusy(false)
  }

  async function removeSaved(name) {
    try {
      await api.deleteSavedFile(name)
      setSaved((xs) => xs.filter((x) => x.name !== name))
      setSavedNote({ text: `Deleted ${name}.` })
    } catch (e) {
      setSavedNote({ error: true, text: e.message })
    }
  }

  const subs = info?.subtitles
  const hasSubs = subs && (subs.manual.length > 0 || subs.auto.length > 0)
  const sizeHint = info
    ? exactBytes ? `${bytes(exactBytes)} total (exact)` : estimate(info.qualities, quality, sel?.codec ?? 'any')
    : ''

  return (
    <div>
      <PageHeader title="Download">
        Save a video, its audio or its subtitles. A playlist or channel link lets you pick several videos.
        {status && (
          <span className="mt-2 block text-sm">
            {status.cookies
              ? <span className="text-ok">Signed in to YouTube ({status.cookies === 'firefox' ? 'cookies read from Firefox' : 'uploaded cookies.txt'}): members-only videos work.</span>
              : <span className="text-ink-faint">Not signed in. Members-only and age-gated videos need <a href="#/settings">YouTube sign-in under Settings</a>.</span>}
            {!status.ffmpeg && <span className="block text-danger">ffmpeg is missing: only single-file formats (usually 720p or lower) can be saved.</span>}
          </span>
        )}
      </PageHeader>

      <form
        className="flex max-w-3xl flex-col gap-3 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault()
          fetchInfo(url.trim())
        }}
      >
        <label htmlFor="dl-url" className="sr-only">YouTube link</label>
        <input
          id="dl-url"
          type="url"
          inputMode="url"
          required
          autoComplete="off"
          spellCheck="false"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=…  or a playlist / channel link"
          className="field font-serif text-lg"
        />
        <button type="submit" className="btn shrink-0 justify-center px-6" disabled={loading || busy}>
          {loading ? 'Looking…' : 'Get formats'}
        </button>
      </form>

      <div aria-live="polite" className="mt-6 max-w-3xl">
        {loading && <p className="pulse text-sm text-ink-soft">Reading the available formats…</p>}
        {error && <p className="text-sm whitespace-pre-line text-danger" role="alert">{error}</p>}
      </div>

      {info && (
        <div className="mt-8 max-w-3xl space-y-8">
          {info.kind === 'video' ? (
            <div className="flex flex-col gap-5 border-t border-rule pt-6 sm:flex-row">
              {info.thumbnail && <img src={info.thumbnail} alt="" className="aspect-video w-full rounded-[3px] object-cover sm:w-56" />}
              <div className="min-w-0">
                <h2 className="font-serif text-[1.5rem] leading-tight text-balance">
                  <a href={info.url} target="_blank" rel="noreferrer" className="text-ink no-underline hover:underline">{info.title}</a>
                </h2>
                <p className="mt-1 text-sm text-ink-soft">
                  {[info.uploader, duration(info.duration)].filter(Boolean).join(' · ')}
                </p>
                <p className="mt-3 text-sm">
                  <a href={toolLink('summarize', info.url)}>Summarize this video</a>
                </p>
              </div>
            </div>
          ) : (
            <div className="border-t border-rule pt-6">
              <h2 className="font-serif text-[1.5rem] leading-tight">{info.title}</h2>
              {isChannelUrl(url) && (
                <p className="mt-1 text-sm">
                  <a href={toolLink('channels', url)}>Follow this channel by email</a>
                  {' · '}
                  <a href={toolLink('summarize', url)}>Summarize its latest videos</a>
                </p>
              )}
              {info.note && <p className="mt-1 text-sm text-ink-faint">{info.note}</p>}
              <div className="mt-4">
                <PlaylistPicker info={info} selected={selected} onChange={setSelected} disabled={busy} />
              </div>
            </div>
          )}

          <div className="space-y-5">
            {info.kind === 'video' && info.note && <p className="text-sm text-danger">{info.note}</p>}
            <QualityPicker
              qualities={info.qualities}
              quality={quality}
              codec={sel?.codec ?? 'any'}
              onQuality={setQuality}
              onCodec={setCodec}
              sizeHint={info.kind === 'playlist' && sizeHint ? `${sizeHint}, first video` : sizeHint}
            />

            {info.kind === 'video' && hasSubs && (
              <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
                <label className="block">
                  <span className="text-sm font-semibold">Subtitles</span>
                  <select className="field mt-1.5 w-auto max-w-72" value={subLang} onChange={(e) => setSubLang(e.target.value)}>
                    <option value="">None</option>
                    {subs.manual.length > 0 && (
                      <optgroup label="Uploaded by the channel">
                        {subs.manual.map((s) => <option key={`m-${s.code}`} value={s.code}>{s.name ? `${s.name} (${s.code})` : s.code}</option>)}
                      </optgroup>
                    )}
                    {subs.auto.length > 0 && (
                      <optgroup label="Automatic captions and translations">
                        {subs.auto.map((s) => <option key={`a-${s.code}`} value={s.code}>{s.name ? `${s.name} (${s.code})` : s.code}</option>)}
                      </optgroup>
                    )}
                  </select>
                </label>
                {sel?.kind === 'video' && (
                  <label className="flex items-center gap-2 pb-2.5 text-sm text-ink-soft">
                    <input type="checkbox" checked={withSubs} onChange={(e) => setWithSubs(e.target.checked)} className="accent-[var(--ink)]" />
                    Save as .srt with the video
                  </label>
                )}
                <button type="button" className="btn btn-quiet" disabled={busy || !subLang} onClick={downloadSubsOnly}>
                  Subtitles only
                </button>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-rule pt-5">
              <button
                type="button"
                className="btn px-6"
                disabled={busy || (info.kind === 'playlist' && !selected.size)}
                onClick={info.kind === 'playlist' ? downloadPlaylist : downloadVideo}
              >
                {busy ? 'Downloading…' : info.kind === 'playlist' ? `Download ${selected.size} video${selected.size === 1 ? '' : 's'}` : 'Download'}
              </button>
              <label className="flex items-center gap-2 text-sm text-ink-soft">
                <input type="checkbox" checked={keep} onChange={(e) => setKeepPersist(e.target.checked)} className="accent-[var(--ink)]" />
                Also keep a copy on the server
              </label>
              {busy && queue && (
                <button type="button" className="btn-text text-sm underline" onClick={() => { stopRef.current = true }}>
                  Stop after this video
                </button>
              )}
            </div>

            {job && info.kind === 'video' && <JobProgress job={job} />}
            {queue && <Queue items={queue} />}
          </div>
        </div>
      )}

      <div className="mt-16">
        <Section
          id="saved"
          title="Saved on the server"
          intro="Downloads made with “keep a copy” stay in data/downloads until you delete them. Others are removed once your browser has them."
        >
          <Notice note={savedNote} />
          {saved === null && <p className="pulse text-sm text-ink-soft">Loading…</p>}
          {saved?.length === 0 && <p className="text-sm text-ink-soft">Nothing saved yet.</p>}
          {saved?.length > 0 && (
            <ul className="mt-2 divide-y divide-rule border-y border-rule text-sm">
              {saved.map((f) => (
                <li key={f.name} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-2.5">
                  <a href={api.savedFileUrl(f.name)} className="min-w-0 flex-1 break-words">{f.name}</a>
                  <span className="text-ink-faint">{bytes(f.size)} · {timeAgo(new Date(f.modified * 1000).toISOString())}</span>
                  <button type="button" className="btn-text text-sm" onClick={() => removeSaved(f.name)}>Delete</button>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
    </div>
  )
}
