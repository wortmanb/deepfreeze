import React from 'react';
import { EuiText, EuiSpacer, EuiProgress } from '@elastic/eui';
import type { RestoreProgress } from '../../common/types';

interface Props {
  repos: RestoreProgress[];
}

/**
 * Renders S3 restore progress bars for each repository in a thaw request.
 */
export default function ProgressPanel({ repos }: Props) {
  return (
    <>
      {repos.map((rp, i) => {
        const pct = rp.total > 0 ? Math.round((rp.restored / rp.total) * 100) : 0;
        return (
          <div key={i} style={{ marginBottom: 16 }}>
            <EuiText size="s"><strong>{rp.repo}</strong></EuiText>
            <EuiSpacer size="xs" />
            <EuiProgress
              value={rp.restored}
              max={rp.total}
              size="m"
              color={rp.complete ? 'success' : 'primary'}
            />
            <EuiSpacer size="xs" />
            <EuiText size="xs" color="subdued">
              {rp.restored}/{rp.total} restored ({pct}%)
              {rp.in_progress > 0 && ` · ${rp.in_progress} in progress`}
              {rp.not_restored > 0 && ` · ${rp.not_restored} pending`}
              {rp.complete && ' · Complete'}
              {rp.error && ` · Error: ${rp.error}`}
            </EuiText>
          </div>
        );
      })}
    </>
  );
}
