import { codecsFor } from './selection.js'

const CODECS = [
  { id: 'any', label: 'Auto (best)' },
  { id: 'avc', label: 'H.264 · MP4' },
  { id: 'vp9', label: 'VP9 · WebM' },
  { id: 'av1', label: 'AV1' },
]
const AUDIO = [
  { id: 'best', label: 'Best audio (as served)' },
  { id: 'm4a', label: 'M4A (AAC)' },
  { id: 'opus', label: 'Opus (WebM)' },
  { id: 'mp3', label: 'MP3 (converted)', needsFfmpeg: true },
]

export default function QualityPicker({ qualities, quality, codec, onQuality, onCodec, sizeHint }) {
  const offered = codecsFor(qualities, quality)
  const audioOnly = quality.startsWith('a-')
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <label className="block">
        <span className="text-sm font-semibold">Resolution or audio</span>
        <select className="field mt-1.5" value={quality} onChange={(e) => onQuality(e.target.value)}>
          {qualities.heights.length > 0 && (
            <optgroup label="Video">
              <option value="best">Best available</option>
              {qualities.heights.map((h) => <option key={h.h} value={String(h.h)}>{h.h}p</option>)}
            </optgroup>
          )}
          <optgroup label="Audio only">
            {AUDIO.filter((a) => !a.needsFfmpeg || qualities.ffmpeg).map((a) => (
              <option key={a.id} value={`a-${a.id}`}>{a.label}</option>
            ))}
          </optgroup>
        </select>
      </label>
      <label className="block">
        <span className="text-sm font-semibold">Codec and container</span>
        <select
          className="field mt-1.5"
          value={offered.includes(codec) ? codec : 'any'}
          onChange={(e) => onCodec(e.target.value)}
          disabled={audioOnly}
        >
          {CODECS.map((c) => (
            <option key={c.id} value={c.id} disabled={!offered.includes(c.id)}>{c.label}</option>
          ))}
        </select>
      </label>
      <p className="min-h-5 text-sm text-ink-soft sm:col-span-2" aria-live="polite">{sizeHint}</p>
    </div>
  )
}
