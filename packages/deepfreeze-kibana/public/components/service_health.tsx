import React, { useState, useEffect } from 'react';
import { EuiHealth, EuiToolTip, EuiText } from '@elastic/eui';
import { api } from '../api/client';

/**
 * Small health indicator that shows Deepfreeze service connectivity
 * in the app header. Polls every 30 seconds.
 */
export default function ServiceHealth() {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [detail, setDetail] = useState('Checking...');

  useEffect(() => {
    const check = async () => {
      try {
        const ready = await api.getReady();
        setHealthy(ready.ready && ready.es_connected);
        setDetail(
          ready.ready
            ? `Connected (ES: ${ready.es_connected ? 'ok' : 'disconnected'})`
            : 'Service not ready'
        );
      } catch (err) {
        setHealthy(false);
        setDetail(err instanceof Error ? err.message : 'Cannot reach Deepfreeze service');
      }
    };

    check();
    const interval = setInterval(check, 30000);
    return () => clearInterval(interval);
  }, []);

  const color = healthy === null ? 'subdued' : healthy ? 'success' : 'danger';

  return (
    <EuiToolTip content={detail}>
      <EuiHealth color={color}>
        <EuiText size="xs">Deepfreeze</EuiText>
      </EuiHealth>
    </EuiToolTip>
  );
}
