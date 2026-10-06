import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import styles from './SetupScreen.module.css'

interface Props {
  country: string
  currency: string
  starting: boolean
  onCountryChange: (c: string) => void
  onStart: () => void
  onAnalytics?: () => void
}

type Provider = 'anthropic' | 'bedrock' | 'azgateway'

interface LlmConfig {
  provider: Provider
  apiKey: string
  region: string
  accessKey: string
  secretKey: string
  baseUrl: string
  bearerToken: string
}

const STORAGE_KEY = 'llm_config'

const DEFAULT_CONFIG: LlmConfig = {
  provider: 'anthropic',
  apiKey: '',
  region: 'us-east-1',
  accessKey: '',
  secretKey: '',
  baseUrl: '',
  bearerToken: '',
}

const COUNTRIES = [
  { code: 'GB', flag: '🇬🇧', name: 'United Kingdom', currency: 'GBP' },
  { code: 'US', flag: '🇺🇸', name: 'United States', currency: 'USD' },
  { code: 'AU', flag: '🇦🇺', name: 'Australia', currency: 'AUD' },
  { code: 'CA', flag: '🇨🇦', name: 'Canada', currency: 'CAD' },
  { code: 'DE', flag: '🇩🇪', name: 'Germany', currency: 'EUR' },
  { code: 'FR', flag: '🇫🇷', name: 'France', currency: 'EUR' },
  { code: 'JP', flag: '🇯🇵', name: 'Japan', currency: 'JPY' },
  { code: 'IN', flag: '🇮🇳', name: 'India', currency: 'INR' },
] as const

const PROVIDERS: { id: Provider; label: string }[] = [
  { id: 'anthropic', label: 'Anthropic API' },
  { id: 'bedrock', label: 'AWS Bedrock' },
  { id: 'azgateway', label: 'Enterprise Gateway (Bedrock)' },
]

const STEPS = [
  { num: '01', title: 'Chat', text: 'Start a conversation with the AI agent' },
  { num: '02', title: 'Scan', text: 'Walk your library once, scanning every shelf' },
  { num: '03', title: 'Get packet', text: 'Receive a priced inventory packet in under 5 minutes' },
] as const

type Tone = 'burgundy' | 'forest' | 'navy' | 'amber' | 'olive' | 'rust' | 'plum' | 'slate'

const SPINES: { left: string; top: string; w: number; h: number; rot: number; tone: Tone; delay: string; dur: string; drift: 'drifta' | 'driftb' | 'driftc' }[] = [
  { left: '2%',  top: '7%',  w: 16, h: 132, rot: -14, tone: 'burgundy', delay: '0s',   dur: '28s', drift: 'drifta' },
  { left: '7%',  top: '58%', w: 14, h: 108, rot: 9,   tone: 'forest',   delay: '-6s',  dur: '34s', drift: 'driftb' },
  { left: '13%', top: '22%', w: 18, h: 156, rot: -5,  tone: 'navy',     delay: '-12s', dur: '31s', drift: 'driftc' },
  { left: '18%', top: '74%', w: 13, h: 96,  rot: 16,  tone: 'amber',    delay: '-3s',  dur: '26s', drift: 'drifta' },
  { left: '78%', top: '10%', w: 17, h: 144, rot: 11,  tone: 'plum',     delay: '-8s',  dur: '33s', drift: 'driftb' },
  { left: '86%', top: '48%', w: 15, h: 120, rot: -10, tone: 'olive',    delay: '-15s', dur: '29s', drift: 'driftc' },
  { left: '92%', top: '18%', w: 14, h: 110, rot: 7,   tone: 'rust',     delay: '-2s',  dur: '36s', drift: 'drifta' },
  { left: '83%', top: '76%', w: 16, h: 138, rot: -7,  tone: 'slate',    delay: '-10s', dur: '30s', drift: 'driftb' },
  { left: '4%',  top: '38%', w: 12, h: 88,  rot: 18,  tone: 'rust',     delay: '-18s', dur: '27s', drift: 'driftc' },
  { left: '95%', top: '62%', w: 13, h: 102, rot: -16, tone: 'burgundy', delay: '-5s',  dur: '35s', drift: 'drifta' },
]

const MOTES = [
  { left: '22%', top: '30%', delay: '0s',   size: 3 },
  { left: '41%', top: '18%', delay: '-3s',  size: 2 },
  { left: '63%', top: '42%', delay: '-7s',  size: 3 },
  { left: '54%', top: '70%', delay: '-11s', size: 2 },
  { left: '70%', top: '22%', delay: '-9s',  size: 3 },
]

function loadConfig(): LlmConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_CONFIG
    return { ...DEFAULT_CONFIG, ...(JSON.parse(raw) as Partial<LlmConfig>) }
  } catch { return DEFAULT_CONFIG }
}

export function SetupScreen({ country, currency, starting, onCountryChange, onStart, onAnalytics }: Props) {
  const [configOpen, setConfigOpen] = useState(false)
  const [config, setConfig] = useState<LlmConfig>(DEFAULT_CONFIG)
  const [saved, setSaved] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const pickerRef = useRef<HTMLDivElement>(null)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => { setConfig(loadConfig()) }, [])

  useEffect(() => {
    if (!pickerOpen) return
    const onDown = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) setPickerOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setPickerOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [pickerOpen])

  useEffect(() => () => { if (saveTimer.current) clearTimeout(saveTimer.current) }, [])

  const patch = useCallback(<K extends keyof LlmConfig>(key: K, value: LlmConfig[K]) => {
    setConfig(prev => ({ ...prev, [key]: value }))
    setSaved(false)
  }, [])

  const saveConfig = useCallback(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(config))
    setSaved(true)
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => setSaved(false), 2200)
  }, [config])

  const selected = COUNTRIES.find(c => c.code === country) ?? COUNTRIES[0]

  return (
    <div className={styles.root}>
      {/* Animated background */}
      <div className={styles.atmosphere} aria-hidden="true">
        <div className={styles.wash} />
        <div className={styles.lamp} />
        <div className={styles.floorGlow} />
        <div className={styles.vignette} />
        {SPINES.map((s, i) => (
          <span
            key={i}
            className={`${styles.spine} ${styles[s.tone]} ${styles[s.drift]}`}
            style={{ left: s.left, top: s.top, width: s.w, height: s.h, animationDelay: s.delay, animationDuration: s.dur, '--rot': `${s.rot}deg` } as CSSProperties}
          />
        ))}
        {MOTES.map((m, i) => (
          <span key={i} className={styles.mote} style={{ left: m.left, top: m.top, width: m.size, height: m.size, animationDelay: m.delay }} />
        ))}
        <div className={styles.grain} />
      </div>

      <div className={styles.frame}>
        {/* Topbar */}
        <header className={styles.topbar}>
          <div className={styles.brand}>
            <span className={styles.mark} aria-hidden="true">
              <span className={styles.markSpine} />
              <span className={styles.markSpine} />
              <span className={styles.markSpine} />
            </span>
            <div>
              <p className={styles.wordmark}>Library Contents Claim</p>
              <p className={styles.brandTag}>Insurance inventory</p>
            </div>
          </div>

          <button
            type="button"
            className={`${styles.configTrigger} ${configOpen ? styles.configTriggerOpen : ''}`}
            aria-expanded={configOpen}
            onClick={() => setConfigOpen(o => !o)}
          >
            ⚙ Configure AI Provider
            <span className={styles.chevron} aria-hidden="true" />
          </button>
        </header>

        {/* AI Config accordion */}
        <div className={`${styles.accordion} ${configOpen ? styles.accordionOpen : ''}`}>
          <div className={styles.accordionClip}>
            <div className={styles.configPanel}>
              <p className={styles.configKicker}>Model access</p>
              <p className={styles.configHint}>Choose where the agent sends requests. Keys never leave this browser.</p>

              <div className={styles.providers} role="radiogroup">
                {PROVIDERS.map(p => (
                  <label key={p.id} className={`${styles.provider} ${config.provider === p.id ? styles.providerOn : ''}`}>
                    <input type="radio" name="llm-provider" value={p.id} checked={config.provider === p.id} onChange={() => patch('provider', p.id)} />
                    {p.label}
                  </label>
                ))}
              </div>

              {config.provider === 'anthropic' && (
                <div className={styles.fields}>
                  <label className={`${styles.field} ${styles.fieldFull}`}>
                    <span>API key</span>
                    <input type="password" autoComplete="off" placeholder="sk-ant-…" value={config.apiKey} onChange={e => patch('apiKey', e.target.value)} />
                  </label>
                </div>
              )}
              {config.provider === 'bedrock' && (
                <div className={styles.fields}>
                  <label className={styles.field}><span>Region</span><input type="text" placeholder="us-east-1" value={config.region} onChange={e => patch('region', e.target.value)} /></label>
                  <label className={styles.field}><span>Access key</span><input type="text" placeholder="AKIA…" value={config.accessKey} onChange={e => patch('accessKey', e.target.value)} /></label>
                  <label className={`${styles.field} ${styles.fieldFull}`}><span>Secret key</span><input type="password" placeholder="Secret access key" value={config.secretKey} onChange={e => patch('secretKey', e.target.value)} /></label>
                </div>
              )}
              {config.provider === 'azgateway' && (
                <div className={styles.fields}>
                  <label className={styles.field}><span>Base URL</span><input type="url" placeholder="https://gateway.example.com" value={config.baseUrl} onChange={e => patch('baseUrl', e.target.value)} /></label>
                  <label className={styles.field}><span>Bearer token</span><input type="password" placeholder="Token" value={config.bearerToken} onChange={e => patch('bearerToken', e.target.value)} /></label>
                </div>
              )}

              <div className={styles.configFooter}>
                <button type="button" className={styles.saveBtn} onClick={saveConfig}>{saved ? '✓ Saved' : 'Save'}</button>
                <p className={styles.localNote}>Stored locally in your browser only</p>
              </div>
            </div>
          </div>
        </div>

        {/* Main content */}
        <main className={styles.main}>
          <section className={styles.hero}>
            <p className={styles.eyebrow}>AI insurance agent · camera sweep</p>
            <h1 className={styles.heroTitle}>
              Photograph the shelves.
              <em> Walk away with a claim.</em>
            </h1>
            <p className={styles.lede}>
              An agent that inventories a home library by camera — titles, editions and
              values — then builds a priced packet the insurer can actually use.
            </p>

            <ol className={styles.steps}>
              {STEPS.map(step => (
                <li key={step.num} className={styles.step}>
                  <span className={styles.stepNum}>{step.num}</span>
                  <div className={styles.stepBody}>
                    <strong>{step.title}</strong>
                    <span>{step.text}</span>
                  </div>
                </li>
              ))}
            </ol>

            <section className={styles.actions}>
              <div className={styles.locale}>
                <span className={styles.localeLabel}>Country &amp; currency</span>
                <div className={styles.picker} ref={pickerRef}>
                  <button
                    type="button"
                    className={`${styles.pickerBtn} ${pickerOpen ? styles.pickerBtnOpen : ''}`}
                    aria-haspopup="listbox"
                    aria-expanded={pickerOpen}
                    onClick={() => setPickerOpen(o => !o)}
                  >
                    <span className={styles.flag}>{selected.flag}</span>
                    <span className={styles.pickerName}>{selected.name}</span>
                    <span className={styles.pickerCur}>{selected.currency}</span>
                    <span className={styles.pickerCaret} aria-hidden="true" />
                  </button>
                  {pickerOpen && (
                    <ul className={styles.menu} role="listbox">
                      {COUNTRIES.map(item => (
                        <li key={item.code}>
                          <button
                            type="button"
                            role="option"
                            aria-selected={item.code === selected.code}
                            className={`${styles.option} ${item.code === selected.code ? styles.optionOn : ''}`}
                            onClick={() => { onCountryChange(item.code); setPickerOpen(false) }}
                          >
                            <span className={styles.flag}>{item.flag}</span>
                            <span className={styles.pickerName}>{item.name}</span>
                            <span className={styles.pickerCur}>{item.currency}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <p className={styles.priced}>Inventories priced in {currency}</p>
              </div>

              <div className={styles.ctaCol}>
                <button type="button" className={styles.startBtn} onClick={onStart} disabled={starting}>
                  {starting ? 'Starting…' : 'Start Sweep →'}
                </button>
                <button type="button" className={styles.historyLink} onClick={() => onAnalytics?.()}>
                  View History &amp; Evidence
                </button>
              </div>
            </section>
          </section>

          {/* Decorative stacked books */}
          <aside className={styles.stack} aria-hidden="true">
            <span className={styles.book} />
          </aside>
        </main>
      </div>
    </div>
  )
}
