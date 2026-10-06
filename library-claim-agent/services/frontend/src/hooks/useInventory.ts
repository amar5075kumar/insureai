/**
 * useInventory — subscribes to WebSocket and maintains live inventory state.
 * Uses the shared useWebSocket hook (single connection per sweepId).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useWebSocket } from './useWebSocket'

export interface Book {
  id: string
  status: 'processing' | 'identified' | 'unidentified' | 'needs_appraisal' | 'low_confidence'
  title?: string
  author?: string
  isbn?: string
  edition?: string
  id_confidence?: number        // OCR + book match confidence (0–1)
  detection_confidence?: number  // YOLO vision detection confidence (0–1)
  spine_height_cm?: number
  spine_thickness_cm?: number
  replacement_cost?: { amount: number; source: string; url: string }
  used_value?: { amount: number; source: string; condition_assumed: string }
  frame_ref?: string
  crop_url?: string
}

export interface Item {
  id: string
  category: string
  description?: string
  status: string
  confidence?: number
  replacement_cost?: { low: number; high: number; source: string }
}

function mergeById<T extends { id: string }>(existing: T[], incoming: T[]): T[] {
  const map = new Map(existing.map((x) => [x.id, x]))
  for (const item of incoming) {
    map.set(item.id, { ...(map.get(item.id) ?? {}), ...item } as T)
  }
  return Array.from(map.values())
}

export function useInventory(sweepId: string | null) {
  const [books, setBooks] = useState<Book[]>([])
  const [items, setItems] = useState<Item[]>([])
  const [processingProgress, setProcessingProgress] = useState(0)
  const [qualityWarning, setQualityWarning] = useState<string | null>(null)
  const [packetUrl, setPacketUrl] = useState<string | null>(null)

  const { addListener, removeListener, sendMessage } = useWebSocket(sweepId)
  const sendMessageRef = useRef(sendMessage)
  sendMessageRef.current = sendMessage

  useEffect(() => {
    if (!sweepId) return

    const onInventoryUpdate = (msg: any) => {
      if (msg.books) setBooks((prev) => mergeById(prev, msg.books))
      if (msg.items) setItems((prev) => mergeById(prev, msg.items))
    }

    const onQualityWarning = (msg: any) => {
      setQualityWarning(msg.message as string)
      setTimeout(() => setQualityWarning(null), 3000)
    }

    const onProcessingProgress = (msg: any) => {
      const pct = (msg.completed / Math.max(1, msg.total)) * 100
      setProcessingProgress(pct)
    }

    const onSweepComplete = (msg: any) => {
      setPacketUrl(msg.packet_url as string)
    }

    addListener('inventory_update', onInventoryUpdate)
    addListener('quality_warning', onQualityWarning)
    addListener('processing_progress', onProcessingProgress)
    addListener('sweep_complete', onSweepComplete)

    return () => {
      removeListener('inventory_update', onInventoryUpdate)
      removeListener('quality_warning', onQualityWarning)
      removeListener('processing_progress', onProcessingProgress)
      removeListener('sweep_complete', onSweepComplete)
    }
  }, [sweepId, addListener, removeListener])

  const sendText = useCallback((text: string) => {
    sendMessageRef.current({ type: 'user_text', text })
  }, [])

  const sendSweepEnd = useCallback(() => {
    sendMessageRef.current({ type: 'sweep_end' })
  }, [])

  return {
    books,
    items,
    processingProgress,
    qualityWarning,
    packetUrl,
    sendText,
    sendSweepEnd,
  }
}
