import { duration } from '../../format.js'

/** Checklist of playlist / channel entries. `selected` is a Set of video ids. */
export default function PlaylistPicker({ info, selected, onChange, disabled }) {
  const all = info.entries.map((e) => e.id)
  const toggle = (id) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(next)
  }
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="text-sm text-ink-soft">
          {selected.size} of {info.entries.length} selected
          {info.entries_count > info.entries.length && ` (playlist has ${info.entries_count})`}
        </p>
        <div className="flex gap-4 text-sm">
          <button type="button" className="btn-text underline" onClick={() => onChange(new Set(all))} disabled={disabled}>
            Select all
          </button>
          <button type="button" className="btn-text underline" onClick={() => onChange(new Set())} disabled={disabled}>
            Select none
          </button>
        </div>
      </div>
      <ul className="mt-3 max-h-96 divide-y divide-rule overflow-y-auto rounded-md border border-rule">
        {info.entries.map((e) => (
          <li key={e.id}>
            <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-raised">
              <input
                type="checkbox"
                checked={selected.has(e.id)}
                onChange={() => toggle(e.id)}
                disabled={disabled}
                className="size-4 shrink-0 accent-[var(--ink)]"
              />
              <img src={e.thumbnail} alt="" loading="lazy" className="aspect-video w-24 shrink-0 rounded-[3px] object-cover" />
              <span className="min-w-0 flex-1 text-sm">
                <span className="line-clamp-2">{e.title}</span>
                {e.duration ? <span className="text-ink-faint">{duration(e.duration)}</span> : null}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  )
}
