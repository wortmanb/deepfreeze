/**
 * Shared types between server and public plugin code.
 * These mirror the Deepfreeze service API response shapes.
 */

// -- Health --

export interface ServiceHealth {
  status: string;
  uptime_seconds?: number;
}

export interface ServiceReady {
  ready: boolean;
  es_connected: boolean;
  cache_age_seconds: number | null;
}

// -- Cluster & Status --

export interface ClusterHealth {
  name: string;
  status: 'green' | 'yellow' | 'red';
  version: string;
  node_count: number;
}

export interface SystemStatus {
  cluster: ClusterHealth;
  settings: Record<string, unknown> | null;
  repositories: Repository[];
  thaw_requests: ThawRequest[];
  buckets: BucketInfo[];
  ilm_policies: IlmPolicyInfo[];
  initialized: boolean;
  errors: ServiceError[];
  timestamp: string;
}

export interface Repository {
  name: string;
  bucket: string;
  base_path: string;
  start: string | null;
  end: string | null;
  is_mounted: boolean;
  thaw_state: 'active' | 'frozen' | 'thawing' | 'thawed' | 'expired';
  storage_tier?: string;
  thawed_at?: string | null;
  expires_at?: string | null;
}

export interface ThawRequest {
  request_id: string;
  status: 'in_progress' | 'completed' | 'failed' | 'refrozen';
  start_date: string;
  end_date: string;
  repos: string[];
  created_at: string;
  repositories?: Record<string, unknown>[];
}

export interface BucketInfo {
  name: string;
  object_count: number;
}

export interface IlmPolicyInfo {
  name: string;
  repository: string;
  indices_count: number;
  data_streams_count: number;
  templates_count?: number;
}

// -- Actions --

export interface ServiceError {
  code: string;
  message: string;
  target?: string | null;
  remediation?: string | null;
  severity: 'error' | 'warning';
}

export interface CommandResult {
  success: boolean;
  action: string;
  dry_run: boolean;
  summary: string;
  details: ActionDetail[];
  errors: ServiceError[];
  raw_output: string;
  started_at: string;
  completed_at: string | null;
  duration_ms: number;
}

export interface ActionDetail {
  type: string;
  action: string;
  target: string;
  status: string;
  metadata?: Record<string, unknown>;
}

// -- Jobs --

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface JobProgress {
  percent: number;
  message: string;
  steps: string[];
}

export interface Job {
  id: string;
  type: string;
  status: JobStatus;
  params: Record<string, unknown>;
  submitted_at: string;
  started_at: string | null;
  completed_at: string | null;
  progress: JobProgress;
  result: CommandResult | null;
  error: ServiceError | null;
  submitted_by: string;
}

export interface JobSubmission {
  job_id: string;
  status: string;
}

// -- Scheduler --

export interface ScheduledJob {
  name: string;
  action: string;
  params: Record<string, unknown>;
  cron: string | null;
  interval_seconds: number | null;
  paused: boolean;
  next_run: string | null;
  persisted: boolean;
}

// -- Restore Progress --

export interface RestoreProgress {
  repo: string;
  total: number;
  restored: number;
  in_progress: number;
  not_restored: number;
  complete: boolean;
  error?: string;
}

// -- Audit --

export interface AuditEntry {
  timestamp: string;
  action: string;
  dry_run: boolean;
  success: boolean;
  duration_ms: number;
  parameters: Record<string, unknown>;
  results: Record<string, unknown>[];
  errors: ServiceError[];
  summary: Record<string, unknown>;
  user: string;
  hostname: string;
  version: string;
}

// -- History --

export interface ActionHistoryEntry {
  timestamp: string;
  action: string;
  dry_run: boolean;
  success: boolean;
  summary: string;
  error_count: number;
}

// -- Plugin Config --

export interface DeepfreezeConfig {
  enabled: boolean;
  serviceUrl: string;
  serviceToken?: string;
}
