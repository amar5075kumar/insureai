/**
 * AgentVoice — plays TTS audio + surfaces transcript text.
 * Uses shared useWebSocket hook (no duplicate connection).
 */
import { useEffect, useRef } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'

interface Props {
  sweepId: string
  onTranscript?: (text: string) => void
}

export function AgentVoice({ sweepId, onTranscript }: Props) {
  const audioCtxRef = useRef<AudioContext | null>(null)
  const nextPlayRef = useRef(0)
  const { addListener, removeListener } = useWebSocket(sweepId)
  const onTranscriptRef = useRef(onTranscript)
  onTranscriptRef.current = onTranscript

  useEffect(() => {
    const init = () => {
      if (!audioCtxRef.current) {
        audioCtxRef.current = new AudioContext({ sampleRate: 24000 })
      }
    }
    document.addEventListener('click', init, { once: true })
    document.addEventListener('touchstart', init, { once: true })
    return () => {
      document.removeEventListener('click', init)
      document.removeEventListener('touchstart', init)
    }
  }, [])

  useEffect(() => {
    const onAgentAudio = (msg: any) => {
      const ctx = audioCtxRef.current
      if (!ctx) return

      const b64 = msg.data as string
      const binary = atob(b64)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i)
      }
      const int16 = new Int16Array(bytes.buffer)
      const float32 = new Float32Array(int16.length)
      for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768
      }
      const buf = ctx.createBuffer(1, float32.length, (msg.sample_rate as number) ?? 24000)
      buf.copyToChannel(float32, 0)
      const src = ctx.createBufferSource()
      src.buffer = buf
      src.connect(ctx.destination)
      const now = ctx.currentTime
      const start = Math.max(now, nextPlayRef.current)
      src.start(start)
      nextPlayRef.current = start + buf.duration
    }

    const onAgentText = (msg: any) => {
      onTranscriptRef.current?.(msg.text as string)
    }

    addListener('agent_audio', onAgentAudio)
    addListener('agent_text', onAgentText)

    return () => {
      removeListener('agent_audio', onAgentAudio)
      removeListener('agent_text', onAgentText)
    }
  }, [sweepId, addListener, removeListener])

  return null
}
