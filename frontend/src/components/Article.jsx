import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const PROVIDER_NAMES = { ollama: 'Ollama', openai: 'OpenAI', claude: 'Claude' }

function formatDate(iso) {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

/** One summarized video: a margin rail of facts beside the reading column. */
export default function Article({ video, onDelete }) {
  let paragraphs = 0
  const components = {
    // Highlight the opening paragraph, which carries the gist.
    p: ({ children }) =>
      paragraphs++ === 0 ? (
        <p>
          <span className="lead">{children}</span>
        </p>
      ) : (
        <p>{children}</p>
      ),
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noreferrer">
        {children}
      </a>
    ),
  }

  const published = formatDate(video.published_at) ?? video.published_date
  return (
    <article className="grid gap-x-10 gap-y-4 border-t border-rule pt-8 md:grid-cols-[11rem_minmax(0,1fr)]">
      <aside className="text-sm leading-relaxed text-ink-soft md:pt-1.5">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 md:block">
          {video.channel && (
            <>
              <dt className="sr-only">Channel</dt>
              <dd className="col-span-2 font-semibold text-ink">{video.channel}</dd>
            </>
          )}
          {published && (
            <>
              <dt className="sr-only">Published</dt>
              <dd>{published}</dd>
            </>
          )}
          {video.duration && video.duration !== '—' && (
            <>
              <dt className="sr-only">Length</dt>
              <dd>{video.duration}</dd>
            </>
          )}
        </dl>
        <p className="mt-3 text-ink-faint">
          {video.has_transcript ? 'Summarized from the transcript' : 'No transcript; summarized from the description'}
          {video.provider && (
            <>
              {' '}by {PROVIDER_NAMES[video.provider] ?? video.provider}
              <span className="block break-all">{video.model}</span>
            </>
          )}
        </p>
        {onDelete && (
          <button type="button" className="btn-text mt-3 text-sm" onClick={() => onDelete(video.id)}>
            Remove from library
          </button>
        )}
      </aside>

      <div className="min-w-0">
        <h2 className="max-w-[30ch] font-serif text-[1.75rem] leading-[1.15] font-medium text-balance sm:text-[2rem]">
          <a href={video.url} target="_blank" rel="noreferrer" className="text-ink no-underline hover:underline">
            {video.title}
          </a>
        </h2>
        {video.thumbnail && (
          <a href={video.url} target="_blank" rel="noreferrer" className="mt-5 block max-w-[66ch]" tabIndex={-1}>
            <img
              src={video.thumbnail}
              alt=""
              loading="lazy"
              className="aspect-video w-full rounded-[3px] object-cover"
            />
          </a>
        )}
        <div className="summary mt-6">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {video.summary}
          </ReactMarkdown>
        </div>
      </div>
    </article>
  )
}
