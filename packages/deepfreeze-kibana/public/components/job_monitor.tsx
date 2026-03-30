import React, { useState, useEffect, useCallback } from 'react';
import {
  EuiPanel,
  EuiTitle,
  EuiSpacer,
  EuiFlexGroup,
  EuiFlexItem,
  EuiText,
  EuiBadge,
  EuiProgress,
  EuiButtonIcon,
  EuiEmptyPrompt,
} from '@elastic/eui';
import { api } from '../api/client';
import type { Job } from '../../common/types';

function statusColor(status: string): string {
  switch (status) {
    case 'running': return 'primary';
    case 'pending': return 'warning';
    case 'completed': return 'success';
    case 'failed': return 'danger';
    case 'cancelled': return 'default';
    default: return 'default';
  }
}

/**
 * Live job monitoring panel. Shows running/pending jobs with progress.
 * Auto-refreshes every 5 seconds while there are active jobs.
 */
export default function JobMonitor() {
  const [jobs, setJobs] = useState<Job[]>([]);

  const refresh = useCallback(async () => {
    try {
      const data = await api.getJobs();
      // Show running and pending jobs, plus recently completed (last 5 min)
      const cutoff = new Date(Date.now() - 5 * 60 * 1000).toISOString();
      const relevant = (data.jobs || []).filter(
        (j: Job) =>
          j.status === 'running' ||
          j.status === 'pending' ||
          (j.completed_at && j.completed_at > cutoff)
      );
      setJobs(relevant);
    } catch {
      // Silently fail — this is a non-critical panel
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  if (jobs.length === 0) return null;

  return (
    <EuiPanel hasBorder paddingSize="m">
      <EuiTitle size="xs"><h3>Active Jobs</h3></EuiTitle>
      <EuiSpacer size="s" />
      {jobs.map((job) => (
        <div key={job.id} style={{ marginBottom: 12 }}>
          <EuiFlexGroup alignItems="center" gutterSize="s" responsive={false}>
            <EuiFlexItem grow={false}>
              <EuiBadge color={statusColor(job.status)}>{job.status}</EuiBadge>
            </EuiFlexItem>
            <EuiFlexItem>
              <EuiText size="s">
                <strong>{job.type}</strong>
                {job.progress?.message && (
                  <span style={{ marginLeft: 8, opacity: 0.7 }}>{job.progress.message}</span>
                )}
              </EuiText>
            </EuiFlexItem>
            {job.status === 'running' && (
              <EuiFlexItem grow={false}>
                <EuiButtonIcon
                  iconType="cross"
                  aria-label="Cancel job"
                  color="danger"
                  size="s"
                  onClick={() => api.cancelJob(job.id).then(refresh)}
                />
              </EuiFlexItem>
            )}
          </EuiFlexGroup>
          {job.status === 'running' && job.progress && (
            <>
              <EuiSpacer size="xs" />
              <EuiProgress
                value={job.progress.percent || 0}
                max={100}
                size="s"
                color="primary"
              />
            </>
          )}
        </div>
      ))}
    </EuiPanel>
  );
}
