import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ConnectionState,
  Room,
  RoomEvent,
  VideoPresets,
  type LocalVideoTrack,
} from 'livekit-client'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL ?? 'ws://localhost:7880'

async function fetchToken(sweepId: string): Promise<{ token: string; url: string }> {
  const res = await fetch(`${API_URL}/sweeps/${sweepId}/livekit-token`)
  if (!res.ok) throw new Error(`Token fetch failed: ${res.status}`)
  return res.json()
}

export function useLiveKit(sweepId: string | null) {
  const roomRef = useRef<Room | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isMuted, setIsMuted] = useState(false)

  const connect = useCallback(async () => {
    if (!sweepId || roomRef.current) return
    setError(null)

    try {
      const { token } = await fetchToken(sweepId)

      const room = new Room({
        adaptiveStream: false,
        dynacast: false,
        videoCaptureDefaults: {
          resolution: VideoPresets.h720.resolution,
          facingMode: 'environment',
        },
        audioCaptureDefaults: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      })

      roomRef.current = room

      room.on(RoomEvent.Connected, () => setConnected(true))
      room.on(RoomEvent.Disconnected, () => setConnected(false))
      room.on(RoomEvent.ConnectionStateChanged, (state) => {
        if (state === ConnectionState.Disconnected) setConnected(false)
      })

      // Always use the public URL for the browser connection
      await room.connect(LIVEKIT_URL, token)
      await room.localParticipant.enableCameraAndMicrophone()

      // Attach local video
      const pub = room.localParticipant.getTrackPublicationByName('camera')
      const videoTrack = pub?.videoTrack as LocalVideoTrack | undefined
      if (videoTrack && videoRef.current) {
        videoTrack.attach(videoRef.current)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
    }
  }, [sweepId])

  const disconnect = useCallback(() => {
    roomRef.current?.disconnect()
    roomRef.current = null
    setConnected(false)
  }, [])

  const toggleMute = useCallback(async () => {
    const room = roomRef.current
    if (!room) return
    const enabled = room.localParticipant.isMicrophoneEnabled
    await room.localParticipant.setMicrophoneEnabled(!enabled)
    setIsMuted(enabled)
  }, [])

  useEffect(() => () => { disconnect() }, [disconnect])

  return { videoRef, connected, error, isMuted, connect, disconnect, toggleMute }
}
