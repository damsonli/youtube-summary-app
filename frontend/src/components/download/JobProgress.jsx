import { bytes } from '../../format.js'

/** Progress line + bar for one download job (the shape returned by /api/download/jobs/{id}). */
export function JobProgress({ job }) {
  if (!job) return null
  const indeterminate = job.status === 'queued' || (job.status === 'downloading' && !job.percent)
  const pct = job.status === 'done' || job.status === 'processing' ? 100 : job.percent
  return (
    <div className="text-sm text-ink-soft">
      <p className="flex justify-between gap-4">
        <span className={job.status === 'done' ? 'text-ok' : job.status === 'error' ? 'text-danger' : 'pulse'}>
          {job.status === 'error' ? 'Failed' : job.text}
        </span>
        <span>
          {job.status === 'downloading' && job.percent > 0 && `${job.percent}%`}
          {job.size ? ` · ${bytes(job.size)}` : ''}
        </span>
      </p>
      <Bar pct={pct} indeterminate={indeterminate} />
    </div>
  )
}

export function Bar({ pct, indeterminate }) {
  return (
    <div className="mt-2 h-[3px] w-full overflow-hidden rounded bg-rule" aria-hidden="true">
      <div
        className={`h-full bg-accent transition-[width] duration-500 ${indeterminate ? 'pulse' : ''}`}
        style={{ width: `${indeterminate ? 100 : pct}%` }}
      />
    </div>
  )
}

const STATE_TEXT = { waiting: 'queued', running: 'downloading…', saved: 'saved', error: 'failed' }

/** Per-video status for a playlist run. */
export function Queue({ items }) {
  const done = items.filter((i) => i.state === 'saved' || i.state === 'error').length
  const running = items.find((i) => i.state === 'running')
  const pct = items.length ? ((done + (running ? (running.percent || 0) / 100 : 0)) / items.length) * 100 : 0
  return (
    <div className="text-sm">
      <p className="flex justify-between text-ink-soft">
        <span>{done} of {items.length} finished</span>
        {running && <span>{running.percent || 0}%</span>}
      </p>
      <Bar pct={pct} />
      <ol className="mt-3 divide-y divide-dashed divide-rule">
        {items.map((it) => (
          <li key={it.id} className="flex items-baseline gap-4 py-1.5">
            <span className="min-w-0 flex-1 truncate">{it.title}</span>
            <span
              className={`shrink-0 ${it.state === 'saved' ? 'text-ok' : it.state === 'error' ? 'text-danger' : it.state === 'running' ? 'pulse text-ink' : 'text-ink-faint'}`}
              title={it.error || undefined}
            >
              {it.state === 'error' && it.error ? `failed: ${it.error.slice(0, 60)}` : STATE_TEXT[it.state]}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
