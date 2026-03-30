import { useState, useCallback } from 'react';
import { api } from '../api/client';
import type { SystemStatus } from '../../common/types';

export function useStatus() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (force = false) => {
    try {
      setLoading(true);
      const data = await api.getStatus(force);
      setStatus(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load status');
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-fetch on first use
  if (!status && !error && loading) {
    refresh();
  }

  return { status, loading, error, refresh };
}
