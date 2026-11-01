import { useEffect, useState } from 'react'
import { api } from '../api.js'
import Article from '../components/Article.jsx'

const PAGE = 20

export default function Library() {
  const [items, setItems] = useState(null)
  const [more, setMore] = useState(false)
  const [error, setError] = useState('')

  function applyPage(page, offset) {
    setMore(page.length > PAGE)
    setItems((xs) => [...(offset ? xs : []), ...page.slice(0, PAGE)])
  }

  function load(offset = 0) {
    return api.history(PAGE + 1, offset).then((page) => applyPage(page, offset), (e) => setError(e.message))
  }

  useEffect(() => {
    api.history(PAGE + 1, 0).then((page) => applyPage(page, 0), (e) => setError(e.message))
  }, [])

  async function remove(id) {
    try {
      await api.deleteHistory(id)
      setItems((xs) => xs.filter((x) => x.id !== id))
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div>
      <h1 className="font-serif text-[2.25rem] leading-tight sm:text-[3rem]">Library</h1>
      <p className="mt-3 max-w-[56ch] text-ink-soft">Every summary you have made, newest first.</p>
      {error && <p className="mt-6 text-danger" role="alert">{error}</p>}
      {items === null && !error && <p className="pulse mt-10 text-ink-soft">Loading…</p>}
      {items?.length === 0 && (
        <p className="mt-10 text-ink-soft">
          Nothing here yet. <a href="#/read">Summarize a video</a> and it will be kept here.
        </p>
      )}
      <div className="mt-10 space-y-14">
        {items?.map((v) => <Article key={v.id} video={v} onDelete={remove} />)}
      </div>
      {more && (
        <button type="button" className="btn btn-quiet mt-12" onClick={() => load(items.length)}>
          Show older summaries
        </button>
      )}
    </div>
  )
}
