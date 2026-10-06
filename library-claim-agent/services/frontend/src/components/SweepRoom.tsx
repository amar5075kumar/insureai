/**
 * SweepRoom — the main live sweep UI.
 *
 * Inspired by the Insurance Claim Live Agent Team reference:
 * - Left: Live camera + controls + conversation transcript
 * - Right: Live inventory notebook (books found + pricing)
 */
import { useEffect, useRef, useState } from 'react'
import { useInventory } from '../hooks/useInventory'
import { useCamera } from '../hooks/useCamera'
import { AgentVoice } from './AgentVoice'
import styles from './SweepRoom.module.css'

interface Props {
  sweepId: string
  country: string
  currency: string
  onComplete: (packetUrl: string) => void
}

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

function ConfBadge({ label, value, title }: { label: string; value: number; title: string }) {
  const pct = Math.round(value * 100)
  const color = pct >= 75 ? '#16a34a' : pct >= 50 ? '#d97706' : '#dc2626'
  const bg = pct >= 75 ? '#dcfce7' : pct >= 50 ? '#fef3c7' : '#fee2e2'
  return (
    <span title={title} style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '1px 7px', borderRadius: 10, fontSize: 11, fontWeight: 600,
      background: bg, color,
    }}>
      {label}
      <span style={{ fontWeight: 700 }}>{pct}%</span>
      <span style={{
        display: 'inline-block', width: 28, height: 4,
        background: '#e5e7eb', borderRadius: 2, overflow: 'hidden',
      }}>
        <span style={{
          display: 'block', width: `${pct}%`, height: '100%',
          background: color, borderRadius: 2,
        }} />
      </span>
    </span>
  )
}

export function SweepRoom({ sweepId, country, currency, onComplete }: Props) {
  const { books, items, processingProgress, qualityWarning, packetUrl, sendText, sendSweepEnd } = useInventory(sweepId)

  const handleVoiceTranscript = (text: string, conf: number) => {
    setTranscript(prev => [...prev, { role: 'user', text: `🎙 ${text}` }])
    sendText(text)
  }
  const { videoRef, connected, error, isMuted, voiceActive, connect, disconnect, toggleMute } = useCamera(sweepId, handleVoiceTranscript)
  const [sweepEnded, setSweepEnded] = useState(false)
  const [transcript, setTranscript] = useState<Array<{ role: 'user' | 'agent', text: string }>>([])
  const [textInput, setTextInput] = useState('')
  const transcriptRef = useRef<HTMLDivElement>(null)
  const [detectionFlash, setDetectionFlash] = useState(false)
  const prevBookCount = useRef(0)
  const [bookFilter, setBookFilter] = useState<'all' | 'identified' | 'unidentified'>('all')

  // Flash green border on video when new books are detected
  useEffect(() => {
    if (books.length > prevBookCount.current) {
      prevBookCount.current = books.length
      setDetectionFlash(true)
      const t = setTimeout(() => setDetectionFlash(false), 800)
      return () => clearTimeout(t)
    }
  }, [books.length])

  useEffect(() => { connect() }, [connect])

  // Packet URL is set when sweep_complete arrives — don't auto-navigate,
  // let the user review results at their own pace and click "Start New Sweep"

  // Auto-scroll transcript
  useEffect(() => {
    if (transcriptRef.current) {
      transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight
    }
  }, [transcript])

  const handleEndSweep = async () => {
    setSweepEnded(true)
    sendSweepEnd()
    await fetch(`${API_URL}/sweeps/${sweepId}/end`, { method: 'POST' }).catch(() => {})
  }

  const handleSend = () => {
    const t = textInput.trim()
    if (!t) return
    setTranscript(prev => [...prev, { role: 'user', text: t }])
    sendText(t)
    setTextInput('')
  }

  const identified = books.filter(b => b.status === 'identified' || b.status === 'low_confidence')
  const totalReplacement = books.reduce((s, b) => s + (b.replacement_cost?.amount ?? 0), 0)

  return (
    <div className={styles.root}>
      {/* ─── LEFT PANEL: Camera + Transcript ─────────────────────── */}
      <div className={styles.leftPanel}>
        {/* Top bar */}
        <div className={styles.topBar}>
          <div className={styles.topBarLeft}>
            <span className={styles.liveDot} />
            <span className={styles.liveLabel}>
              {connected ? 'Live, watching' : 'Connecting…'}
            </span>
          </div>
          <div className={styles.topBarTitle}>Library Claim Agent</div>
          {!sweepEnded && (
            <button className={styles.endBtn} onClick={handleEndSweep}>
              ✓ Done
            </button>
          )}
          {sweepEnded && (
            <span className={styles.processingBadge}>
              Processing {Math.round(processingProgress)}%
            </span>
          )}
        </div>

        {/* Camera */}
        <div className={styles.cameraWrap}>
          <video
            ref={videoRef}
            autoPlay muted playsInline
            className={styles.camera}
            style={detectionFlash ? { outline: '3px solid #22c55e', outlineOffset: '-3px' } : undefined}
          />

          {!connected && !error && (
            <div className={styles.cameraOverlay}>
              <div className={styles.cameraSpinner} />
              <p>Connecting camera…</p>
            </div>
          )}

          {error && (
            <div className={styles.cameraError}>
              <span>📷</span>
              <p>Camera unavailable</p>
              <small>{error}</small>
            </div>
          )}

          {/* Quality warning */}
          {qualityWarning && (
            <div className={styles.qualityBanner}>
              ⚠ {qualityWarning}
            </div>
          )}

          {/* Agent watching badge */}
          {connected && (
            <div className={styles.watchingBadge}>
              <span className={styles.recDot} />
              Agent is watching
            </div>
          )}
        </div>

        {/* Camera controls */}
        <div className={styles.controls}>
          <button
            className={`${styles.controlBtn} ${isMuted ? styles.muted : ''}`}
            onClick={toggleMute}
          >
            {isMuted ? '🔇' : '🎙'}
            <span>{isMuted ? 'Muted' : voiceActive ? 'Voice On' : 'Listening'}</span>
          </button>
          {connected && (
            <button
              className={styles.controlBtn}
              onClick={disconnect}
              style={{ background: '#374151', color: '#f3f4f6' }}
            >
              ⏹
              <span>Stop Camera</span>
            </button>
          )}
        </div>

        {/* Transcript */}
        <div className={styles.transcript} ref={transcriptRef}>
          {transcript.length === 0 && (
            <p className={styles.transcriptHint}>
              Agent will respond as you scan your shelves…
            </p>
          )}
          {transcript.map((msg, i) => (
            <div key={i} className={`${styles.msg} ${msg.role === 'agent' ? styles.agentMsg : styles.userMsg}`}>
              <span className={styles.msgRole}>{msg.role === 'agent' ? 'AI' : 'You'}</span>
              <span className={styles.msgText}>{msg.text}</span>
            </div>
          ))}
        </div>

        {/* Text input */}
        <div className={styles.inputRow}>
          <input
            className={styles.textInput}
            placeholder="Or type a correction…"
            value={textInput}
            onChange={e => setTextInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
          />
          <button className={styles.sendBtn} onClick={handleSend}>Send</button>
        </div>
      </div>

      {/* ─── RIGHT PANEL: Live Inventory Notebook ─────────────────── */}
      <div className={styles.rightPanel}>
        <div className={styles.notebookHeader}>
          <div>
            <h2 className={styles.notebookTitle}>Library Inventory</h2>
            <p className={styles.notebookDate}>{new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}</p>
          </div>
          <div className={styles.totalBadge}>
            <div className={styles.totalLabel}>Est. Replacement</div>
            <div className={styles.totalValue}>
              {currency} {totalReplacement.toFixed(0)}
            </div>
          </div>
        </div>

        {/* Stats row */}
        <div className={styles.statsRow}>
          <div className={styles.stat}>
            <div className={styles.statNum}>{books.length}</div>
            <div className={styles.statLabel}>Books found</div>
          </div>
          <div className={styles.stat}>
            <div className={styles.statNum}>{identified.length}</div>
            <div className={styles.statLabel}>Identified</div>
          </div>
          <div className={styles.stat}>
            <div className={styles.statNum}>{items.length}</div>
            <div className={styles.statLabel}>Items</div>
          </div>
          <div className={styles.stat}>
            <div className={styles.statNum}>
              {books.filter(b => b.status === 'processing').length}
            </div>
            <div className={styles.statLabel}>Processing</div>
          </div>
        </div>

        {/* Progress bar while processing */}
        {sweepEnded && processingProgress < 100 && (
          <div className={styles.progressWrap}>
            <div className={styles.progressBar}>
              <div className={styles.progressFill} style={{ width: `${processingProgress}%` }} />
            </div>
            <span className={styles.progressLabel}>Workers: {Math.round(processingProgress)}%</span>
          </div>
        )}

        {/* Completion banner — stays on page so user can review at their own pace */}
        {sweepEnded && processingProgress >= 100 && (
          <div style={{
            margin: '12px 16px', padding: '16px 20px', borderRadius: 12,
            background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)',
            border: '1.5px solid #16a34a', display: 'flex', alignItems: 'center',
            justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
          }}>
            <div>
              <div style={{ fontWeight: 700, color: '#15803d', fontSize: 15 }}>
                ✓ Sweep complete
              </div>
              <div style={{ fontSize: 13, color: '#166534', marginTop: 2 }}>
                {identified.length} book{identified.length !== 1 ? 's' : ''} identified
                {' · '}{currency} {totalReplacement.toFixed(0)} est. replacement
                {packetUrl && ' · Claim packet ready'}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {packetUrl && (
                <a
                  href={`${API_URL}${packetUrl}`}
                  download
                  style={{
                    padding: '8px 16px', borderRadius: 8, fontWeight: 600,
                    fontSize: 13, textDecoration: 'none',
                    background: '#16a34a', color: '#fff',
                  }}
                >
                  ⬇ Download Packet
                </a>
              )}
              <button
                onClick={() => { disconnect(); onComplete(packetUrl ?? '') }}
                style={{
                  padding: '8px 16px', borderRadius: 8, fontWeight: 600,
                  fontSize: 13, border: '1.5px solid #16a34a',
                  background: '#fff', color: '#16a34a', cursor: 'pointer',
                }}
              >
                Start New Sweep
              </button>
            </div>
          </div>
        )}

        {/* Filter tabs */}
        <div style={{ display: 'flex', gap: 8, padding: '8px 16px', borderBottom: '1px solid #e5e7eb' }}>
          {(['all', 'identified', 'unidentified'] as const).map(f => (
            <button
              key={f}
              onClick={() => setBookFilter(f)}
              style={{
                padding: '4px 12px', borderRadius: 20, border: 'none', cursor: 'pointer', fontSize: 13,
                background: bookFilter === f ? '#1f2937' : '#f3f4f6',
                color: bookFilter === f ? '#fff' : '#374151',
                fontWeight: bookFilter === f ? 600 : 400,
              }}
            >
              {f === 'all' ? `All (${books.length})` :
               f === 'identified' ? `Identified (${books.filter(b => b.status === 'identified' || b.status === 'low_confidence').length})` :
               `Unidentified (${books.filter(b => b.status === 'unidentified').length})`}
            </button>
          ))}
        </div>

        {/* Book entries — notebook style */}
        <div className={styles.bookList}>
          {books.length === 0 && (
            <div className={styles.emptyState}>
              <span>📚</span>
              <p>Books will appear here as you scan your shelves</p>
            </div>
          )}
          {books
            .filter(b =>
              bookFilter === 'all' ? true :
              bookFilter === 'identified' ? (b.status === 'identified' || b.status === 'low_confidence') :
              b.status === 'unidentified'
            )
            .map((book, i) => (
            <div
              key={book.id}
              className={`${styles.bookEntry} ${
                book.status === 'identified' ? styles.identified :
                book.status === 'needs_appraisal' ? styles.appraisal :
                book.status === 'processing' ? styles.processing : styles.unidentified
              }`}
            >
              <div className={styles.bookNum}>{i + 1}</div>
              {book.crop_url && (
                <img
                  src={`${API_URL}${book.crop_url}`}
                  alt="spine crop"
                  style={{ width: 32, height: 48, objectFit: 'cover', borderRadius: 3, marginRight: 6, flexShrink: 0, border: '1px solid #e5e7eb' }}
                />
              )}
              <div className={styles.bookInfo}>
                <div className={styles.bookTitle}>
                  {book.title ?? (
                    book.status === 'processing'
                      ? <span className={styles.skeleton}>Identifying…</span>
                      : <span className={styles.unknown}>Spine unreadable</span>
                  )}
                </div>
                {book.author && <div className={styles.bookAuthor}>{book.author}</div>}
                {/* Confidence indicators */}
                {(book.detection_confidence || book.id_confidence) && (
                  <div style={{ display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                    {book.detection_confidence != null && (
                      <ConfBadge
                        label="Vision"
                        value={book.detection_confidence}
                        title="YOLO detection confidence — how sure the model is this is a book"
                      />
                    )}
                    {book.id_confidence != null && book.status !== 'unidentified' && (
                      <ConfBadge
                        label="OCR"
                        value={book.id_confidence}
                        title="OCR + book match confidence — how accurately Claude read the spine"
                      />
                    )}
                  </div>
                )}
              </div>
              <div className={styles.bookPrice}>
                {book.replacement_cost ? (
                  <>
                    <div className={styles.priceValue}>
                      {currency} {book.replacement_cost.amount.toFixed(2)}
                    </div>
                    <div className={styles.priceSource}>{book.replacement_cost.source}</div>
                  </>
                ) : book.status === 'identified' ? (
                  <span className={styles.pricingDot}>pricing…</span>
                ) : book.status === 'needs_appraisal' ? (
                  <span className={styles.appraisalTag}>Appraisal</span>
                ) : null}
              </div>
            </div>
          ))}

          {/* Non-book items */}
          {items.length > 0 && (
            <div className={styles.itemsSection}>
              <h3 className={styles.itemsTitle}>Other Items</h3>
              <div className={styles.itemTags}>
                {items.map(item => (
                  <span key={item.id} className={styles.itemTag}>
                    {item.category}
                    {item.replacement_cost
                      ? ` · ${currency} ${item.replacement_cost.low.toFixed(0)}`
                      : ''}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Agent audio (invisible) */}
      <AgentVoice sweepId={sweepId} onTranscript={t => setTranscript(prev => [...prev, { role: 'agent', text: t }])} />
    </div>
  )
}
