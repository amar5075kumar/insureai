/**
 * useDirectCamera — local dev camera without WebRTC.
 *
 * Uses getUserMedia() directly (works on localhost without HTTPS).
 * Captures frames every N seconds and POSTs them to /webhooks/frame.
 * Also streams audio PCM to /webhooks/audio via MediaRecorder.
 *
 * Activated when VITE_CAMERA_MODE=direct (default for local dev).
 * On cloud, switch to VITE_CAMERA_MODE=livekit which uses useLiveKit.ts.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const FRAME_INTERVAL_MS = parseInt(import.meta.env.VITE_FRAME_INTERVAL_MS ?? '3000')

// Extend Window type for Web Speech API
declare global {
  interface Window {
    SpeechRecognition: typeof SpeechRecognition
    webkitSpeechRecognition: typeof SpeechRecognition
  }
}

export function useDirectCamera(
  sweepId: string | null,
  onTranscript?: (text: string, confidence: number) => void,
) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const frameTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const frameCountRef = useRef(0)
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const onTranscriptRef = useRef(onTranscript)
  onTranscriptRef.current = onTranscript

  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isMuted, setIsMuted] = useState(false)
  const [voiceActive, setVoiceActive] = useState(false)

  const connect = useCallback(async () => {
    if (!sweepId || streamRef.current) return
    setError(null)

    try {
      // Request camera + mic
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          facingMode: 'environment', // back camera on mobile
        },
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      })

      streamRef.current = stream
      setConnected(true)

      // Attach video to element
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        await videoRef.current.play().catch(() => {})
      }

      // Create offscreen canvas for frame capture
      canvasRef.current = document.createElement('canvas')

      // Start frame capture loop
      frameTimerRef.current = setInterval(async () => {
        await captureAndSendFrame(sweepId)
      }, FRAME_INTERVAL_MS)

      // Start Web Speech API recognition
      const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition
      if (SpeechRecognitionAPI) {
        const rec = new SpeechRecognitionAPI()
        rec.continuous = true
        rec.interimResults = false
        rec.lang = 'en-US'  // Change to 'hi-IN' for Hindi
        rec.onresult = (event: SpeechRecognitionEvent) => {
          const result = event.results[event.results.length - 1]
          if (result.isFinal) {
            const text = result[0].transcript.trim()
            const conf = result[0].confidence
            if (text && onTranscriptRef.current) {
              onTranscriptRef.current(text, conf ?? 1.0)
            }
          }
        }
        rec.onerror = (e: SpeechRecognitionErrorEvent) => {
          if (e.error !== 'no-speech' && e.error !== 'aborted') {
            console.warn('Speech recognition error:', e.error)
          }
        }
        rec.onend = () => {
          // Auto-restart unless disconnected
          if (streamRef.current) {
            try { rec.start() } catch {}
          }
        }
        recognitionRef.current = rec
        try { rec.start(); setVoiceActive(true) } catch {}
      }

    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
      setConnected(false)
    }
  }, [sweepId])

  const captureAndSendFrame = async (sid: string) => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || video.readyState < 2) return

    canvas.width = video.videoWidth || 640
    canvas.height = video.videoHeight || 480
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.drawImage(video, 0, 0)

    canvas.toBlob(async (blob) => {
      if (!blob) return
      const frameId = `frame_${Date.now()}_${frameCountRef.current++}`
      const form = new FormData()
      form.append('sweep_id', sid)
      form.append('frame_id', frameId)
      form.append('timestamp_ms', String(Date.now()))
      form.append('jpeg_data', blob, 'frame.jpg')

      await fetch(`${API_URL}/webhooks/frame`, {
        method: 'POST',
        body: form,
      }).catch(() => {}) // Silent fail — network issues shouldn't break UI
    }, 'image/jpeg', 0.85)
  }

  const disconnect = useCallback(() => {
    if (frameTimerRef.current) {
      clearInterval(frameTimerRef.current)
      frameTimerRef.current = null
    }
    if (recognitionRef.current) {
      try { recognitionRef.current.stop() } catch {}
      recognitionRef.current = null
      setVoiceActive(false)
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
    setConnected(false)
  }, [])

  const toggleMute = useCallback(() => {
    const stream = streamRef.current
    if (!stream) return
    const audioTrack = stream.getAudioTracks()[0]
    if (!audioTrack) return
    audioTrack.enabled = !audioTrack.enabled
    setIsMuted(!audioTrack.enabled)
  }, [])

  // Cleanup on unmount
  useEffect(() => () => { disconnect() }, [disconnect])

  return { videoRef, connected, error, isMuted, voiceActive, connect, disconnect, toggleMute }
}
