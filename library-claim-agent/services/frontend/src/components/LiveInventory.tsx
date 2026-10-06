/**
 * LiveInventory — shows books and items detected during the sweep.
 * Updates in real time as the WebSocket pushes inventory_update messages.
 */
import type { Book, Item } from '../hooks/useInventory'

interface Props {
  books: Book[]
  items: Item[]
  currency: string
  processingProgress: number
  isProcessing: boolean
}

const statusColour: Record<string, string> = {
  identified: '#d4edda',
  unidentified: '#fff3cd',
  needs_appraisal: '#f8d7da',
  low_confidence: '#ffeeba',
  processing: '#e2e3e5',
}

export function LiveInventory({
  books,
  items,
  currency,
  processingProgress,
  isProcessing,
}: Props) {
  const identified = books.filter(b => b.status === 'identified').length
  const unidentified = books.filter(b => b.status === 'unidentified').length
  const processing = books.filter(b => b.status === 'processing').length

  return (
    <div style={{ padding: '1rem', overflowY: 'auto', maxHeight: '80vh' }}>
      <h2 style={{ margin: '0 0 0.5rem' }}>
        Library Inventory
        <span style={{ fontWeight: 'normal', fontSize: '0.8em', marginLeft: '0.5rem', color: '#666' }}>
          ({books.length} books)
        </span>
      </h2>

      {processing > 0 && (
        <div style={{ color: '#666', marginBottom: '0.5rem', fontSize: '0.85em' }}>
          ⟳ Identifying {processing} books…
        </div>
      )}

      {isProcessing && (
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.85em', color: '#555', marginBottom: '0.25rem' }}>
            Processing workers: {processingProgress}%
          </div>
          <div style={{
            height: '6px', background: '#e0e0e0', borderRadius: '3px', overflow: 'hidden'
          }}>
            <div style={{
              width: `${processingProgress}%`,
              height: '100%',
              background: '#007bff',
              transition: 'width 0.5s ease',
            }} />
          </div>
        </div>
      )}

      {/* Books list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
        {books.map((book) => (
          <div
            key={book.id}
            style={{
              background: statusColour[book.status] ?? '#f9f9f9',
              padding: '0.5rem 0.75rem',
              borderRadius: '6px',
              fontSize: '0.85em',
            }}
          >
            <div style={{ fontWeight: 600, color: '#333' }}>
              {book.title ?? (book.status === 'processing' ? '…identifying…' : 'Book (unreadable spine)')}
            </div>
            {book.author && (
              <div style={{ color: '#555' }}>{book.author}</div>
            )}
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.2rem' }}>
              <span style={{ color: '#888', fontSize: '0.9em' }}>
                {book.spine_height_cm ? `${book.spine_height_cm.toFixed(1)}cm` : ''}
                {book.id_confidence ? ` · ${Math.round(book.id_confidence * 100)}% conf` : ''}
              </span>
              {book.replacement_cost ? (
                <span style={{ fontWeight: 500, color: '#2d6a4f' }}>
                  {currency} {book.replacement_cost.amount.toFixed(2)}
                </span>
              ) : book.status === 'identified' ? (
                <span style={{ color: '#aaa', fontSize: '0.9em' }}>pricing…</span>
              ) : null}
            </div>
          </div>
        ))}
      </div>

      {/* Items section */}
      {items.length > 0 && (
        <div style={{ marginTop: '1rem' }}>
          <h3 style={{ margin: '0 0 0.5rem', fontSize: '0.95em', color: '#555' }}>
            Other Items ({items.length})
          </h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.4rem' }}>
            {items.map((item) => (
              <span
                key={item.id}
                style={{
                  background: '#e2e3e5',
                  padding: '0.2rem 0.6rem',
                  borderRadius: '12px',
                  fontSize: '0.8em',
                  color: '#333',
                }}
              >
                {item.category}
                {item.replacement_cost
                  ? ` · ${currency} ${item.replacement_cost.low.toFixed(0)}–${item.replacement_cost.high.toFixed(0)}`
                  : ''}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
