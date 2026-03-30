/**
 * Browser-side API client for the Deepfreeze Kibana plugin.
 *
 * All requests go to /api/deepfreeze/* which are proxied by the
 * Kibana server plugin to the Deepfreeze service. No direct
 * browser-to-service communication.
 */

import { API_BASE } from '../../common';
import type {
  SystemStatus,
  CommandResult,
  RestoreProgress,
  AuditEntry,
  ActionHistoryEntry,
  ScheduledJob,
  ServiceHealth,
  ServiceReady,
} from '../../common/types';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', 'kbn-xsrf': 'true', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(error.message || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  // Health
  getHealth: () => request<ServiceHealth>('/health'),
  getReady: () => request<ServiceReady>('/ready'),

  // Status
  getStatus: (forceRefresh = false) =>
    request<SystemStatus>(`/status?force_refresh=${forceRefresh}`),

  getRepositories: () =>
    request<{ repositories: SystemStatus['repositories'] }>('/status/repositories'),

  getThawRequests: () =>
    request<{ thaw_requests: SystemStatus['thaw_requests'] }>('/status/thaw-requests'),

  getBuckets: () =>
    request<{ buckets: SystemStatus['buckets'] }>('/status/buckets'),

  getIlmPolicies: () =>
    request<{ ilm_policies: SystemStatus['ilm_policies'] }>('/status/ilm-policies'),

  getRestoreProgress: (requestId: string) =>
    request<{ request_id: string; repos: RestoreProgress[] }>(
      `/thaw-requests/${requestId}/restore-progress`,
    ),

  getHistory: (limit = 25) =>
    request<{ history: ActionHistoryEntry[] }>(`/history?limit=${limit}`),

  getAuditLog: (limit = 50, action?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (action) params.set('action', action);
    return request<{ entries: AuditEntry[]; source: string }>(`/audit?${params}`);
  },

  // Actions
  rotate: (params: { year?: number; month?: number; keep?: number; dry_run?: boolean }) =>
    request<CommandResult>('/actions/rotate', {
      method: 'POST',
      body: JSON.stringify(params),
    }),

  thawCreate: (params: {
    start_date: string;
    end_date: string;
    duration?: number;
    tier?: string;
    dry_run?: boolean;
  }) =>
    request<CommandResult>('/actions/thaw', {
      method: 'POST',
      body: JSON.stringify(params),
    }),

  thawCheck: (requestId?: string) =>
    request<CommandResult>('/actions/thaw/check', {
      method: 'POST',
      body: JSON.stringify({ request_id: requestId }),
    }),

  refreeze: (params: { request_id?: string; dry_run?: boolean }) =>
    request<CommandResult>('/actions/refreeze', {
      method: 'POST',
      body: JSON.stringify(params),
    }),

  cleanup: (params: { refrozen_retention_days?: number; dry_run?: boolean }) =>
    request<CommandResult>('/actions/cleanup', {
      method: 'POST',
      body: JSON.stringify(params),
    }),

  repair: (params: { dry_run?: boolean }) =>
    request<CommandResult>('/actions/repair', {
      method: 'POST',
      body: JSON.stringify(params),
    }),

  // Scheduler
  getScheduledJobs: () =>
    request<{ jobs: ScheduledJob[] }>('/scheduler/jobs'),

  addScheduledJob: (job: { name: string; action: string; params?: Record<string, unknown>; cron?: string; interval_seconds?: number }) =>
    request<ScheduledJob>('/scheduler/jobs', {
      method: 'POST',
      body: JSON.stringify(job),
    }),

  updateScheduledJob: (name: string, job: { name: string; action: string; params?: Record<string, unknown>; cron?: string; interval_seconds?: number }) =>
    request<ScheduledJob>(`/scheduler/jobs/${encodeURIComponent(name)}`, {
      method: 'PUT',
      body: JSON.stringify(job),
    }),

  removeScheduledJob: (name: string) =>
    request<{ name: string; status: string }>(`/scheduler/jobs/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  pauseScheduledJob: (name: string) =>
    request<{ name: string; status: string }>(`/scheduler/jobs/${encodeURIComponent(name)}/pause`, {
      method: 'POST',
    }),

  resumeScheduledJob: (name: string) =>
    request<{ name: string; status: string }>(`/scheduler/jobs/${encodeURIComponent(name)}/resume`, {
      method: 'POST',
    }),
};
