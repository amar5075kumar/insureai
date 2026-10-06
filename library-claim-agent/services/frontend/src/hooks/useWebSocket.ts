import { useEffect, useCallback, useRef } from 'react'

const WS_URL = (import.meta.env.VITE_API_URL ?? 'http://localhost:8000').replace('http', 'ws')

interface SharedSocket {
  ws: WebSocket | null
  refCount: number
  listeners: Map<string, Set<(data: any) => void>>
  reconnectDelay: number
  reconnectTimer: ReturnType<typeof setTimeout> | null
  destroyed: boolean
}

const sockets = new Map<string, SharedSocket>()

function createSocket(sweepId: string): SharedSocket {
  const shared: SharedSocket = {
    ws: null,
    refCount: 0,
    listeners: new Map(),
    reconnectDelay: 500,
    reconnectTimer: null,
    destroyed: false,
  }

  function connect() {
    if (shared.destroyed) return

    const ws = new WebSocket(`${WS_URL}/ws/${sweepId}`)
    shared.ws = ws

    ws.onopen = () => {
      shared.reconnectDelay = 500
    }

    ws.onmessage = (event) => {
      let msg: Record<string, unknown>
      try {
        msg = JSON.parse(event.data)
      } catch {
        return
      }
      const msgType = msg.type as string | undefined
      if (!msgType) return
      const fns = shared.listeners.get(msgType)
      if (fns) {
        fns.forEach((fn) => fn(msg))
      }
    }

    ws.onclose = () => {
      if (shared.destroyed) return
      shared.ws = null
      scheduleReconnect()
    }

    ws.onerror = () => {
      // onclose fires after onerror — reconnect happens there
    }
  }

  function scheduleReconnect() {
    if (shared.destroyed || shared.reconnectTimer) return
    shared.reconnectTimer = setTimeout(() => {
      shared.reconnectTimer = null
      connect()
      shared.reconnectDelay = Math.min(shared.reconnectDelay * 2, 5000)
    }, shared.reconnectDelay)
  }

  connect()
  return shared
}

function destroySocket(sweepId: string, shared: SharedSocket) {
  shared.destroyed = true
  if (shared.reconnectTimer) {
    clearTimeout(shared.reconnectTimer)
    shared.reconnectTimer = null
  }
  if (shared.ws) {
    shared.ws.onclose = null
    shared.ws.onerror = null
    shared.ws.onmessage = null
    shared.ws.close()
    shared.ws = null
  }
  sockets.delete(sweepId)
}

export function useWebSocket(sweepId: string | null) {
  const listenersRef = useRef<Map<string, Set<(data: any) => void>>>(new Map())

  useEffect(() => {
    if (!sweepId) return

    let shared = sockets.get(sweepId)
    if (!shared) {
      shared = createSocket(sweepId)
      sockets.set(sweepId, shared)
    }
    shared.refCount++

    return () => {
      shared!.refCount--
      if (shared!.refCount <= 0) {
        destroySocket(sweepId, shared!)
      }
    }
  }, [sweepId])

  const addListener = useCallback(
    (type: string, fn: (data: any) => void) => {
      if (!sweepId) return
      const shared = sockets.get(sweepId)
      if (!shared) return

      if (!shared.listeners.has(type)) {
        shared.listeners.set(type, new Set())
      }
      shared.listeners.get(type)!.add(fn)

      if (!listenersRef.current.has(type)) {
        listenersRef.current.set(type, new Set())
      }
      listenersRef.current.get(type)!.add(fn)
    },
    [sweepId]
  )

  const removeListener = useCallback(
    (type: string, fn: (data: any) => void) => {
      if (!sweepId) return
      const shared = sockets.get(sweepId)
      if (!shared) return

      const fns = shared.listeners.get(type)
      if (fns) {
        fns.delete(fn)
        if (fns.size === 0) shared.listeners.delete(type)
      }

      const localFns = listenersRef.current.get(type)
      if (localFns) {
        localFns.delete(fn)
        if (localFns.size === 0) listenersRef.current.delete(type)
      }
    },
    [sweepId]
  )

  const sendMessage = useCallback(
    (data: object) => {
      if (!sweepId) return
      const shared = sockets.get(sweepId)
      if (!shared?.ws || shared.ws.readyState !== WebSocket.OPEN) return
      shared.ws.send(JSON.stringify(data))
    },
    [sweepId]
  )

  // Clean up all listeners registered by this hook instance on unmount
  useEffect(() => {
    return () => {
      if (!sweepId) return
      const shared = sockets.get(sweepId)
      if (!shared) return
      listenersRef.current.forEach((fns, type) => {
        const sharedFns = shared.listeners.get(type)
        if (sharedFns) {
          fns.forEach((fn) => sharedFns.delete(fn))
          if (sharedFns.size === 0) shared.listeners.delete(type)
        }
      })
      listenersRef.current.clear()
    }
  }, [sweepId])

  return { addListener, removeListener, sendMessage }
}
