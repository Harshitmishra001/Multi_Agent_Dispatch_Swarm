/**
 * useDisasterSocket – real-time event hook for the Disaster Coordinator frontend.
 *
 * Connects to ws://[host]/ws and exposes the latest event plus a connection
 * status flag.  The hook reconnects automatically after disconnects with
 * exponential back-off (capped at 30 s).
 *
 * @example
 * const { lastEvent, connected } = useDisasterSocket();
 * // lastEvent: { event: "NEED_UPDATED", need_id: "...", status: "completed" }
 */

import { useCallback, useEffect, useRef, useState } from 'react';

const BASE_DELAY_MS = 1_000;
const MAX_DELAY_MS = 30_000;

function buildWsUrl() {
  // Works whether the app is served on HTTP or HTTPS
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = import.meta.env.VITE_API_WS_HOST || window.location.host;
  return `${protocol}//${host}/ws`;
}

export function useDisasterSocket(onEvent) {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);

  const wsRef = useRef(null);
  const retryRef = useRef(null);
  const delayRef = useRef(BASE_DELAY_MS);
  const onEventRef = useRef(onEvent);

  // Keep callback ref fresh without re-triggering the effect
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  const connect = useCallback(() => {
    const url = buildWsUrl();
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      delayRef.current = BASE_DELAY_MS; // reset back-off on successful connect
    };

    ws.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        setLastEvent(payload);
        onEventRef.current?.(payload);
      } catch {
        // Ignore unparseable frames
      }
    };

    ws.onclose = () => {
      setConnected(false);
      // Exponential back-off reconnect
      retryRef.current = setTimeout(() => {
        delayRef.current = Math.min(delayRef.current * 2, MAX_DELAY_MS);
        connect();
      }, delayRef.current);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, lastEvent };
}
