import { useEffect, useRef, useCallback, useState } from 'react';
import { API_BASE } from '../../common';

export type EventChannel = 'jobs' | 'status' | 'thaw' | 'scheduler';

export interface DeepfreezeEvent {
  event: string;
  data: Record<string, unknown>;
}

interface UseEventsOptions {
  channel?: EventChannel;
  onEvent?: (event: DeepfreezeEvent) => void;
  enabled?: boolean;
}

/**
 * Hook to subscribe to Deepfreeze SSE events via the Kibana proxy.
 *
 * Automatically reconnects on connection loss with exponential backoff.
 * Returns the latest event and connection status.
 */
export function useEvents({ channel, onEvent, enabled = true }: UseEventsOptions = {}) {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<DeepfreezeEvent | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelayRef = useRef(1000);

  const connect = useCallback(() => {
    if (!enabled) return;

    // Build URL
    let url = `${API_BASE}/events`;
    if (channel) {
      url += `?channel=${channel}`;
    }

    // Add kbn-xsrf as query param since EventSource doesn't support custom headers
    url += (url.includes('?') ? '&' : '?') + 'kbn-xsrf=true';

    const source = new EventSource(url);
    sourceRef.current = source;

    source.onopen = () => {
      setConnected(true);
      retryDelayRef.current = 1000; // Reset backoff on success
    };

    source.onmessage = (e) => {
      try {
        const parsed: DeepfreezeEvent = {
          event: e.type || 'message',
          data: JSON.parse(e.data),
        };
        setLastEvent(parsed);
        onEvent?.(parsed);
      } catch {
        // Ignore malformed events
      }
    };

    source.onerror = () => {
      setConnected(false);
      source.close();
      sourceRef.current = null;

      // Reconnect with exponential backoff (max 30s)
      const delay = Math.min(retryDelayRef.current, 30000);
      retryRef.current = setTimeout(() => {
        retryDelayRef.current = delay * 1.5;
        connect();
      }, delay);
    };
  }, [channel, enabled, onEvent]);

  useEffect(() => {
    connect();
    return () => {
      sourceRef.current?.close();
      sourceRef.current = null;
      if (retryRef.current) {
        clearTimeout(retryRef.current);
        retryRef.current = null;
      }
    };
  }, [connect]);

  return { connected, lastEvent };
}
