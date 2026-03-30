import React from 'react';
import { EuiBadge } from '@elastic/eui';

const COLOR_MAP: Record<string, string> = {
  // Thaw request status
  completed: 'success',
  in_progress: 'warning',
  pending: 'warning',
  failed: 'danger',
  refrozen: 'primary',
  // Repo thaw state
  active: 'success',
  frozen: 'primary',
  thawing: 'warning',
  thawed: 'success',
  expired: 'danger',
  // Job status
  running: 'primary',
  cancelled: 'default',
};

interface Props {
  status: string;
}

export default function StatusBadge({ status }: Props) {
  const color = COLOR_MAP[status] || 'default';
  return <EuiBadge color={color}>{status}</EuiBadge>;
}
