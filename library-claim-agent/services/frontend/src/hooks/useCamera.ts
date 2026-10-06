/**
 * useCamera — unified camera hook.
 *
 * Selects the right implementation based on VITE_CAMERA_MODE:
 *   direct  (default) — getUserMedia + HTTP frames  → works locally in WSL2
 *   livekit             — WebRTC via LiveKit         → use on cloud/production
 *
 * Both hooks expose the same interface so SweepRoom.tsx never changes.
 */
import { useDirectCamera } from './useDirectCamera'
import { useLiveKit } from './useLiveKit'

const CAMERA_MODE = import.meta.env.VITE_CAMERA_MODE ?? 'direct'

export function useCamera(
  sweepId: string | null,
  onTranscript?: (text: string, confidence: number) => void,
) {
  // Hook rules: both are always called, only one is used.
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const direct = useDirectCamera(sweepId, onTranscript)
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const livekit = useLiveKit(sweepId)

  return CAMERA_MODE === 'livekit' ? livekit : direct
}
