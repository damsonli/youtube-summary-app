import { bytes } from '../../format.js'

/** 'best' | '720' | 'a-m4a' + codec -> the structured selection the server accepts. */
export function selectionFor(quality, codec) {
  if (quality.startsWith('a-')) return { kind: 'audio', mode: quality.slice(2) }
  return { kind: 'video', height: quality === 'best' ? 'best' : Number(quality), codec }
}

/** Codecs offered at the chosen height ('best' offers every codec seen at any height). */
export function codecsFor(qualities, quality) {
  if (quality.startsWith('a-')) return ['any']
  if (quality === 'best') return ['any', ...new Set(qualities.heights.flatMap((h) => h.codecs.slice(1)))]
  return qualities.heights.find((h) => String(h.h) === quality)?.codecs ?? ['any']
}

/** Size estimate from the format list, shown until the exact size arrives. */
export function estimate(qualities, quality, codec) {
  if (quality.startsWith('a-')) {
    const b = qualities.audio[quality.slice(2)]
    return b ? `≈ ${bytes(b)} (audio)` : ''
  }
  if (quality === 'best') return qualities.best_total ? `≈ ${bytes(qualities.best_total)} total` : 'size unknown'
  const h = qualities.heights.find((x) => String(x.h) === quality)
  const v = h?.sizes[codec] || h?.sizes.any || 0
  return v ? `≈ ${bytes(v + (qualities.audio.best || 0))} total (video + audio)` : 'size unknown'
}

