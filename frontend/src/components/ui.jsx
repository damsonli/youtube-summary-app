/* Small shared pieces for the Channels and Settings pages. */

export function PageHeader({ title, children }) {
  return (
    <div className="mb-10">
      <h1 className="font-serif text-[2.25rem] leading-tight sm:text-[3rem]">{title}</h1>
      {children && <div className="mt-3 max-w-[60ch] text-[1.0625rem] leading-relaxed text-ink-soft">{children}</div>}
    </div>
  )
}

/** A titled block: heading in the left rail on wide screens, content on the right. */
export function Section({ title, intro, id, children }) {
  return (
    <section id={id} className="grid scroll-mt-6 gap-x-10 gap-y-4 border-t border-rule pt-7 pb-4 md:grid-cols-[12rem_minmax(0,1fr)]">
      <div>
        <h2 className="font-serif text-[1.375rem] leading-snug">{title}</h2>
        {intro && <p className="mt-2 text-sm leading-relaxed text-ink-soft">{intro}</p>}
      </div>
      <div className="min-w-0 max-w-2xl">{children}</div>
    </section>
  )
}

/**
 * A labelled form field. `source` is 'ui' when the value was changed on this page,
 * which shows a link to go back to the value from the .env file.
 */
export function Field({ label, help, error, source, onReset, children, className = '' }) {
  return (
    <div className={className}>
      <label className="block">
        <span className="text-sm font-semibold">{label}</span>
        <span className="mt-1.5 block">{children}</span>
      </label>
      {error && <p className="mt-1 text-sm text-danger">{error}</p>}
      {help && !error && <p className="mt-1 text-sm leading-relaxed text-ink-faint">{help}</p>}
      {source === 'ui' && onReset && (
        <p className="mt-1 text-sm text-ink-faint">
          Changed here.{' '}
          <button type="button" className="btn-text text-sm underline" onClick={onReset}>
            Use the .env value instead
          </button>
        </p>
      )}
    </div>
  )
}

export function Notice({ note }) {
  if (!note) return null
  return (
    <p role={note.error ? 'alert' : 'status'} className={`text-sm ${note.error ? 'text-danger' : 'text-ok'}`}>
      {note.text}
    </p>
  )
}

