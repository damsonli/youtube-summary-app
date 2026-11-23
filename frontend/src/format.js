/* Formatting helpers shared by the views. */

/** "09:00" -> "9:00 AM" in the viewer's locale. */
export function clock(hhmm) {
  const [h, m] = hhmm.split(':').map(Number)
  return new Date(2000, 0, 1, h, m).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function listJoin(items) {
  try {
    return new Intl.ListFormat(undefined, { style: 'long', type: 'conjunction' }).format(items)
  } catch {
    return items.join(', ')
  }
}

export function timeAgo(iso) {
  if (!iso) return null
  const secs = (Date.now() - new Date(iso).getTime()) / 1000
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  if (Math.abs(secs) < 60) return 'just now'
  if (Math.abs(secs) < 3600) return rtf.format(-Math.round(secs / 60), 'minute')
  if (Math.abs(secs) < 86400) return rtf.format(-Math.round(secs / 3600), 'hour')
  return rtf.format(-Math.round(secs / 86400), 'day')
}

export function when(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export function prettyZone(tz) {
  return tz ? tz.replaceAll('_', ' ') : ''
}

/** Link to another tool with a video/channel URL prefilled, e.g. toolLink('download', url). */
export const toolLink = (tool, url) => `#/${tool}?url=${encodeURIComponent(url)}`

/** Seconds -> "1:02:03" / "4:05". */
export function duration(s) {
  if (s === null || s === undefined) return ''
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.round(s % 60)
  return (h ? `${h}:` : '') + String(m).padStart(h ? 2 : 1, '0') + ':' + String(sec).padStart(2, '0')
}

/** Bytes -> "12.3 MB". Empty for 0 / unknown. */
export function bytes(n) {
  if (!n) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`
}
