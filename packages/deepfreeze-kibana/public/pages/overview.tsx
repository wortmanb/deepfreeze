import React, { useState, useEffect, useCallback } from 'react';
import {
  EuiTitle,
  EuiSpacer,
  EuiFlexGroup,
  EuiFlexItem,
  EuiStat,
  EuiPanel,
  EuiHealth,
  EuiLoadingSpinner,
  EuiCallOut,
  EuiButton,
} from '@elastic/eui';
import { api } from '../api/client';
import type { SystemStatus } from '../../common/types';
import JobMonitor from '../components/job_monitor';

export default function Overview() {
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

  useEffect(() => {
    refresh();
    const interval = setInterval(() => refresh(), 60000);
    return () => clearInterval(interval);
  }, [refresh]);

  if (loading && !status) {
    return (
      <EuiFlexGroup justifyContent="center" alignItems="center" style={{ minHeight: 300 }}>
        <EuiFlexItem grow={false}>
          <EuiLoadingSpinner size="xl" />
        </EuiFlexItem>
      </EuiFlexGroup>
    );
  }

  if (error && !status) {
    return (
      <EuiCallOut title="Cannot connect to Deepfreeze service" color="danger" iconType="alert">
        <p>{error}</p>
        <EuiButton color="danger" onClick={() => refresh(true)}>Retry</EuiButton>
      </EuiCallOut>
    );
  }

  const repos = status?.repositories || [];
  const thawRequests = status?.thaw_requests || [];
  const cluster = status?.cluster;

  const frozenCount = repos.filter((r) => r.thaw_state === 'frozen').length;
  const thawedCount = repos.filter((r) => r.thaw_state === 'thawed').length;
  const activeCount = repos.filter((r) => r.thaw_state === 'active').length;
  const inProgressCount = thawRequests.filter((r) => r.status === 'in_progress').length;

  const clusterColor = cluster?.status === 'green' ? 'success' : cluster?.status === 'yellow' ? 'warning' : 'danger';

  return (
    <>
      <EuiFlexGroup justifyContent="spaceBetween" alignItems="center">
        <EuiFlexItem grow={false}>
          <EuiTitle size="l"><h2>Overview</h2></EuiTitle>
        </EuiFlexItem>
        <EuiFlexItem grow={false}>
          <EuiButton iconType="refresh" onClick={() => refresh(true)} isLoading={loading} size="s">
            Refresh
          </EuiButton>
        </EuiFlexItem>
      </EuiFlexGroup>

      <EuiSpacer size="l" />

      {/* Cluster health */}
      {cluster && (
        <>
          <EuiPanel hasBorder paddingSize="l">
            <EuiFlexGroup>
              <EuiFlexItem>
                <EuiHealth color={clusterColor} textSize="m">
                  Cluster: {cluster.name} — {cluster.status}
                </EuiHealth>
              </EuiFlexItem>
              <EuiFlexItem grow={false}>
                ES {cluster.version} · {cluster.node_count} node{cluster.node_count !== 1 ? 's' : ''}
              </EuiFlexItem>
            </EuiFlexGroup>
          </EuiPanel>
          <EuiSpacer size="m" />
        </>
      )}

      {/* Stats */}
      <EuiFlexGroup>
        <EuiFlexItem>
          <EuiPanel hasBorder paddingSize="l">
            <EuiStat title={repos.length} description="Total Repositories" titleColor="primary" />
          </EuiPanel>
        </EuiFlexItem>
        <EuiFlexItem>
          <EuiPanel hasBorder paddingSize="l">
            <EuiStat title={activeCount} description="Active" titleColor="success" />
          </EuiPanel>
        </EuiFlexItem>
        <EuiFlexItem>
          <EuiPanel hasBorder paddingSize="l">
            <EuiStat title={frozenCount} description="Frozen" titleColor="accent" />
          </EuiPanel>
        </EuiFlexItem>
        <EuiFlexItem>
          <EuiPanel hasBorder paddingSize="l">
            <EuiStat title={thawedCount} description="Thawed" titleColor="warning" />
          </EuiPanel>
        </EuiFlexItem>
        <EuiFlexItem>
          <EuiPanel hasBorder paddingSize="l">
            <EuiStat title={inProgressCount} description="Thaws In Progress" titleColor="danger" />
          </EuiPanel>
        </EuiFlexItem>
      </EuiFlexGroup>

      <EuiSpacer size="m" />

      {/* Active jobs */}
      <JobMonitor />

      <EuiSpacer size="m" />

      {!status?.initialized && (
        <EuiCallOut title="Deepfreeze not initialized" color="warning" iconType="alert">
          <p>Run <strong>deepfreeze setup</strong> to initialize the system.</p>
        </EuiCallOut>
      )}
    </>
  );
}
