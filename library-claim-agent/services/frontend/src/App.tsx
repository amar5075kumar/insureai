import { useState } from 'react'
import { SetupScreen } from './components/SetupScreen'
import { SweepRoom } from './components/SweepRoom'
import { CompleteScreen } from './components/CompleteScreen'
import { AnalyticsScreen } from './components/AnalyticsScreen'

type Phase = 'setup' | 'sweep' | 'complete' | 'analytics'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

const COUNTRY_CURRENCY: Record<string, string> = {
  GB: 'GBP', US: 'USD', AU: 'AUD', CA: 'CAD',
  FR: 'EUR', DE: 'EUR', ES: 'EUR', JP: 'JPY', IN: 'INR',
}

export function App() {
  const [phase, setPhase] = useState<Phase>('setup')
  const [sweepId, setSweepId] = useState<string | null>(null)
  const [country, setCountry] = useState('GB')
  const [currency, setCurrency] = useState('GBP')
  const [packetUrl, setPacketUrl] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const handleCountryChange = (c: string) => {
    setCountry(c)
    setCurrency(COUNTRY_CURRENCY[c] ?? 'USD')
  }

  const handleStart = async () => {
    setStarting(true)
    try {
      // Read LLM config saved by ⚙ Configure AI Provider panel
      let llm_config: Record<string, string> | null = null
      try {
        const saved = localStorage.getItem('llm_config')
        if (saved) llm_config = JSON.parse(saved)
      } catch {}

      const res = await fetch(`${API_URL}/sweeps`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ country, currency, llm_config }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setSweepId(data.sweep_id)
      setPhase('sweep')
    } catch (err) {
      alert(`Failed to start sweep: ${err}`)
    } finally {
      setStarting(false)
    }
  }

  const handleComplete = (url: string) => {
    setPacketUrl(url)
    setPhase('complete')
  }

  if (phase === 'analytics') {
    return <AnalyticsScreen onBack={() => setPhase('setup')} />
  }

  if (phase === 'setup') {
    return (
      <SetupScreen
        country={country}
        currency={currency}
        starting={starting}
        onCountryChange={handleCountryChange}
        onStart={handleStart}
        onAnalytics={() => setPhase('analytics')}
      />
    )
  }

  if (phase === 'sweep' && sweepId) {
    return (
      <SweepRoom
        sweepId={sweepId}
        country={country}
        currency={currency}
        onComplete={handleComplete}
      />
    )
  }

  return (
    <CompleteScreen
      sweepId={sweepId!}
      packetUrl={packetUrl}
      onNewSweep={() => { setSweepId(null); setPhase('setup') }}
    />
  )
}
