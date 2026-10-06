/**
 * AnalyticsScreen — session history and evidence viewer.
 * Lists all sweeps with per-session stats and evidence download.
 */
import { useEffect, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

interface SweepSummary {
  sweep_id: string
  state: string
  country: string
  currency: string
  created_at: string | null
  total_books: number
  identified_books: number
  low_confidence_books: number
  unidentified_books: number
  total_items: number
  avg_detection_confidence: number | null
  avg_ocr_confidence: number | null
  total_replacement_value: number | null
  currency_symbol: string
  packet_available: boolean
  packet_url: string | null
}

interface BookDetail {
  id: string
  status: string
  title: string | null
  author: string | null
  isbn: string | null
  id_confidence: number | null
  detection_confidence: number | null
  replacement_cost: number | null
  source: string | null
  language: string | null
  crop_url: string
}

interface SweepDetail extends SweepSummary {
  books: BookDetail[]
}

function ConfBar({ value, label }: { value: number | null; label: string }) {
  if (value == null) return <span style={{ color: '#9ca3af', fontSize: 12 }}>—</span>
  const pct = Math.round(value * 100)
  const color = pct >= 75 ? '#16a34a' : pct >= 50 ? '#d97706' : '#dc2626'
  return (
    <span style={{ fontSize: 12 }}>
      <span style={{ color, fontWeight: 600 }}>{pct}%</span>
      <span style={{ color: '#6b7280' }}> {label}</span>
    </span>
  )
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div style={{
      background: '#f9fafb', borderRadius: 8, padding: '10px 16px',
      border: '1px solid #e5e7eb', minWidth: 100, textAlign: 'center',
    }}>
      <div style={{ fontSize: 22, fontWeight: 700, color: '#111827' }}>{value}</div>
      <div style={{ fontSize: 11, color: '#6b7280', marginTop: 2 }}>{label}</div>
      {sub && <div style={{ fontSize: 10, color: '#9ca3af' }}>{sub}</div>}
    </div>
  )
}

function StateChip({ state }: { state: string }) {
  const map: Record<string, { bg: string; color: string }> = {
    sweeping: { bg: '#dbeafe', color: '#1d4ed8' },
    processing: { bg: '#fef3c7', color: '#d97706' },
    reviewing: { bg: '#ede9fe', color: '#7c3aed' },
    finalizing: { bg: '#fce7f3', color: '#be185d' },
    complete: { bg: '#dcfce7', color: '#15803d' },
    interrupted: { bg: '#fee2e2', color: '#dc2626' },
    failed: { bg: '#fee2e2', color: '#dc2626' },
  }
  const s = map[state] ?? { bg: '#f3f4f6', color: '#374151' }
  return (
    <span style={{
      fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
      background: s.bg, color: s.color,
    }}>{state}</span>
  )
}

function formatDate(dt: string | null) {
  if (!dt) return '—'
  try { return new Date(dt).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) }
  catch { return dt.slice(0, 16) }
}

export function AnalyticsScreen({ onBack }: { onBack: () => void }) {
  const [sweeps, setSweeps] = useState<SweepSummary[]>([])
  const [selected, setSelected] = useState<SweepDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)

  useEffect(() => {
    fetch(`${API_URL}/sweeps`)
      .then(r => r.json())
      .then(setSweeps)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const loadDetail = async (id: string) => {
    setDetailLoading(true)
    try {
      const r = await fetch(`${API_URL}/sweeps/${id}/analytics`)
      setSelected(await r.json())
    } finally {
      setDetailLoading(false)
    }
  }

  const completedCount = sweeps.filter(s => s.total_books > 0).length
  const totalBooksAll = sweeps.reduce((s, x) => s + x.total_books, 0)
  const totalValueAll = sweeps.reduce((s, x) => s + (x.total_replacement_value ?? 0), 0)

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', minHeight: '100vh', background: '#f8fafc' }}>
      {/* Header */}
      <div style={{
        background: '#fff', borderBottom: '1px solid #e5e7eb',
        padding: '16px 24px', display: 'flex', alignItems: 'center', gap: 16,
      }}>
        <button onClick={onBack} style={{
          background: 'none', border: '1px solid #e5e7eb', borderRadius: 8,
          padding: '6px 14px', cursor: 'pointer', fontSize: 14, color: '#374151',
        }}>← Back</button>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: '#111827' }}>Session Analytics</h1>
          <p style={{ margin: 0, fontSize: 13, color: '#6b7280' }}>Evidence history across all library sweeps</p>
        </div>
      </div>

      {/* Top summary */}
      {!loading && sweeps.length > 0 && (
        <div style={{ padding: '20px 24px', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <StatCard label="Total sessions" value={sweeps.length} />
          <StatCard label="Books inventoried" value={totalBooksAll} />
          <StatCard label="Total est. value" value={`£${totalValueAll.toFixed(0)}`} sub="across all sessions" />
          <StatCard label="Sessions w/ books" value={completedCount} />
        </div>
      )}

      <div style={{ display: 'flex', gap: 0, minHeight: 'calc(100vh - 160px)' }}>
        {/* Session list */}
        <div style={{ width: selected ? 380 : '100%', borderRight: '1px solid #e5e7eb', overflow: 'auto' }}>
          {loading && <div style={{ padding: 40, textAlign: 'center', color: '#6b7280' }}>Loading sessions…</div>}
          {!loading && sweeps.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: '#6b7280' }}>No sessions yet.</div>
          )}
          {sweeps.map(s => (
            <div
              key={s.sweep_id}
              onClick={() => loadDetail(s.sweep_id)}
              style={{
                padding: '16px 20px', borderBottom: '1px solid #f3f4f6', cursor: 'pointer',
                background: selected?.sweep_id === s.sweep_id ? '#eff6ff' : '#fff',
                borderLeft: selected?.sweep_id === s.sweep_id ? '3px solid #3b82f6' : '3px solid transparent',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                <div>
                  <StateChip state={s.state} />
                  <span style={{ marginLeft: 8, fontSize: 11, color: '#9ca3af' }}>{s.country} · {s.currency}</span>
                </div>
                {s.total_replacement_value != null && (
                  <span style={{ fontSize: 15, fontWeight: 700, color: '#059669' }}>
                    {s.currency_symbol}{s.total_replacement_value.toFixed(0)}
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 6 }}>{formatDate(s.created_at)}</div>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 12 }}><strong>{s.total_books}</strong> books</span>
                <span style={{ fontSize: 12, color: '#059669' }}><strong>{s.identified_books + s.low_confidence_books}</strong> identified</span>
                <span style={{ fontSize: 12, color: '#9ca3af' }}>{s.unidentified_books} unreadable</span>
                {s.total_items > 0 && <span style={{ fontSize: 12, color: '#7c3aed' }}>{s.total_items} items</span>}
              </div>
              <div style={{ display: 'flex', gap: 12, marginTop: 6 }}>
                <ConfBar value={s.avg_detection_confidence} label="avg vision" />
                <ConfBar value={s.avg_ocr_confidence} label="avg OCR" />
              </div>
              {s.packet_available && (
                <a
                  href={`${API_URL}${s.packet_url}`}
                  download
                  onClick={e => e.stopPropagation()}
                  style={{
                    display: 'inline-block', marginTop: 8, fontSize: 11, fontWeight: 600,
                    color: '#2563eb', textDecoration: 'none', padding: '3px 8px',
                    border: '1px solid #bfdbfe', borderRadius: 6, background: '#eff6ff',
                  }}
                >
                  ⬇ Download Evidence Pack
                </a>
              )}
            </div>
          ))}
        </div>

        {/* Detail panel */}
        {selected && (
          <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
            {detailLoading ? (
              <div style={{ textAlign: 'center', padding: 40, color: '#6b7280' }}>Loading…</div>
            ) : (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                  <div>
                    <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
                      Session Detail <StateChip state={selected.state} />
                    </h2>
                    <p style={{ margin: '4px 0 0', color: '#6b7280', fontSize: 13 }}>
                      {formatDate(selected.created_at)} · {selected.country} · {selected.currency}
                    </p>
                  </div>
                  {selected.packet_available && (
                    <a
                      href={`${API_URL}${selected.packet_url}`}
                      download
                      style={{
                        padding: '8px 16px', background: '#2563eb', color: '#fff',
                        borderRadius: 8, textDecoration: 'none', fontSize: 13, fontWeight: 600,
                      }}
                    >
                      ⬇ Download Evidence Pack
                    </a>
                  )}
                </div>

                {/* Stats row */}
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
                  <StatCard label="Books found" value={selected.total_books} />
                  <StatCard label="Identified" value={selected.identified_books + selected.low_confidence_books} />
                  <StatCard label="Unreadable" value={selected.unidentified_books} />
                  <StatCard label="Items" value={selected.total_items} />
                  <StatCard
                    label="Total value"
                    value={selected.total_replacement_value != null ? `${selected.currency_symbol}${selected.total_replacement_value.toFixed(2)}` : '—'}
                    sub="replacement estimate"
                  />
                  <StatCard
                    label="Avg vision conf"
                    value={selected.avg_detection_confidence != null ? `${Math.round(selected.avg_detection_confidence * 100)}%` : '—'}
                    sub="YOLO detection"
                  />
                  <StatCard
                    label="Avg OCR conf"
                    value={selected.avg_ocr_confidence != null ? `${Math.round(selected.avg_ocr_confidence * 100)}%` : '—'}
                    sub="Claude reading"
                  />
                </div>

                {/* Book table */}
                <h3 style={{ fontSize: 14, fontWeight: 600, color: '#374151', marginBottom: 12 }}>
                  Books ({selected.books?.length ?? 0})
                </h3>
                <div style={{ border: '1px solid #e5e7eb', borderRadius: 8, overflow: 'hidden' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr style={{ background: '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
                        <th style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600, color: '#374151', width: 48 }}>#</th>
                        <th style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600, color: '#374151', width: 48 }}>Crop</th>
                        <th style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600, color: '#374151' }}>Title / Author</th>
                        <th style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600, color: '#374151' }}>ISBN</th>
                        <th style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600, color: '#374151' }}>Confidence</th>
                        <th style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600, color: '#374151' }}>Value</th>
                        <th style={{ padding: '8px 12px', textAlign: 'left', fontWeight: 600, color: '#374151' }}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(selected.books ?? []).map((b, i) => (
                        <tr key={b.id} style={{ borderBottom: '1px solid #f3f4f6', background: i % 2 === 0 ? '#fff' : '#fafafa' }}>
                          <td style={{ padding: '8px 12px', color: '#9ca3af' }}>{i + 1}</td>
                          <td style={{ padding: '6px 12px' }}>
                            <img
                              src={`${API_URL}${b.crop_url}`}
                              alt="spine"
                              style={{ width: 28, height: 42, objectFit: 'cover', borderRadius: 3, border: '1px solid #e5e7eb' }}
                              onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                            />
                          </td>
                          <td style={{ padding: '8px 12px' }}>
                            <div style={{ fontWeight: b.title ? 500 : 400, color: b.title ? '#111827' : '#9ca3af' }}>
                              {b.title ?? 'Spine unreadable'}
                              {b.language && b.language !== 'en' && (
                                <span style={{ marginLeft: 6, fontSize: 10, background: '#ede9fe', color: '#7c3aed', padding: '1px 5px', borderRadius: 8 }}>
                                  {b.language}
                                </span>
                              )}
                            </div>
                            {b.author && <div style={{ fontSize: 11, color: '#6b7280' }}>{b.author}</div>}
                          </td>
                          <td style={{ padding: '8px 12px', fontSize: 11, color: '#6b7280', fontFamily: 'monospace' }}>
                            {b.isbn ?? '—'}
                          </td>
                          <td style={{ padding: '8px 12px' }}>
                            <div style={{ display: 'flex', gap: 6 }}>
                              <ConfBar value={b.detection_confidence} label="V" />
                              <ConfBar value={b.id_confidence} label="O" />
                            </div>
                          </td>
                          <td style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 600, color: '#059669' }}>
                            {b.replacement_cost != null ? `${selected.currency_symbol}${b.replacement_cost.toFixed(2)}` : '—'}
                          </td>
                          <td style={{ padding: '8px 12px' }}>
                            <StateChip state={b.status} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
