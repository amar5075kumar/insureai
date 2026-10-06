const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

interface Props {
  sweepId: string
  packetUrl: string | null
  onNewSweep: () => void
}

export function CompleteScreen({ sweepId, packetUrl, onNewSweep }: Props) {
  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'Inter, system-ui, sans-serif',
    }}>
      <div style={{
        background: 'white', borderRadius: 20, padding: '2.5rem',
        maxWidth: 460, width: '100%', textAlign: 'center',
        boxShadow: '0 25px 60px rgba(0,0,0,0.3)',
      }}>
        <div style={{ fontSize: '4rem', marginBottom: '1rem' }}>{packetUrl ? '✅' : '📚'}</div>
        <h2 style={{ margin: '0 0 0.5rem', color: '#1a1a2e', fontSize: '1.4rem' }}>
          {packetUrl ? 'Sweep Complete' : 'Session Finished'}
        </h2>
        <p style={{ color: '#666', margin: '0 0 2rem', fontSize: '0.9rem' }}>
          {packetUrl
            ? 'Your library inventory is complete. Download the claim packet below.'
            : 'Your sweep has been saved. View session history for full details.'}
        </p>

        {packetUrl && (
          <a
            href={`${API_URL}${packetUrl}`}
            download
            style={{
              display: 'inline-block', padding: '0.9rem 2rem',
              background: 'linear-gradient(135deg, #667eea, #764ba2)',
              color: 'white', textDecoration: 'none',
              borderRadius: 12, fontWeight: 600, fontSize: '1rem',
              marginBottom: '1rem',
            }}
          >
            ⬇ Download Claim Packet (ZIP)
          </a>
        )}

        <br />
        <button
          onClick={onNewSweep}
          style={{
            padding: '0.6rem 1.5rem', background: 'none',
            border: '1px solid #e0e0e0', borderRadius: 10,
            cursor: 'pointer', color: '#555', fontSize: '0.88rem', marginTop: '0.5rem',
          }}
        >
          Start New Sweep
        </button>
      </div>
    </div>
  )
}
