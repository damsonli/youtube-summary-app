export class ApiError extends Error {
  constructor(message, fields = {}) {
    super(message)
    this.fields = fields // { field_name: 'what is wrong' } for form validation errors
  }
}

async function request(path, { method = 'GET', body } = {}) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(errorMessage(data) || `Request failed (${res.status})`, data?.detail?.fields)
  return data
}

function errorMessage(data) {
  const d = data?.detail
  if (!d) return null
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((e) => e.msg?.replace(/^Value error, /, '')).join('; ')
  return d.message ?? null
}

export const api = {
  status: () => request('/status'),
  llm: () => request('/llm'),
  settings: () => request('/settings'),
  saveSettings: (changes) => request('/settings', { method: 'PUT', body: changes }),
  testProvider: (body) => request('/settings/test-provider', { method: 'POST', body }),
  history: (limit = 30, offset = 0) => request(`/history?limit=${limit}&offset=${offset}`),
  deleteHistory: (id) => request(`/history/${id}`, { method: 'DELETE' }),
  subscriptions: (email) => request(`/subscriptions?email=${encodeURIComponent(email)}`),
  subscribe: (body) => request('/subscriptions', { method: 'POST', body }),
  unsubscribe: (id) => request(`/subscriptions/${id}`, { method: 'DELETE' }),
  runCheck: () => request('/check', { method: 'POST' }),
  runs: () => request('/runs'),
  testEmail: (to) => request('/email/test', { method: 'POST', body: { to } }),
}

/** POST /api/analyze and call onEvent for every server-sent event. */
export async function streamAnalyze(body, onEvent, signal) {
  const res = await fetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    throw new Error(errorMessage(data) || `Request failed (${res.status})`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''
    for (const chunk of chunks) {
      const line = chunk.split('\n').find((l) => l.startsWith('data: '))
      if (line) onEvent(JSON.parse(line.slice(6)))
    }
  }
}

export const storage = {
  get(key, fallback = '') {
    try { return localStorage.getItem(key) ?? fallback } catch { return fallback }
  },
  set(key, value) {
    try { localStorage.setItem(key, value) } catch { /* private mode */ }
  },
}

export const isChannelUrl = (url) => /youtube\.com\/(@|channel\/|c\/|user\/)/i.test(url)
