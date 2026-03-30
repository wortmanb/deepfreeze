import React from 'react';
import { EuiTitle, EuiSpacer, EuiCallOut } from '@elastic/eui';

export default function Repositories() {
  return (
    <>
      <EuiTitle size="l"><h2>Repositories</h2></EuiTitle>
      <EuiSpacer size="l" />
      <EuiCallOut title="Coming soon" color="primary" iconType="iInCircle">
        <p>This page will be ported from the standalone Deepfreeze UI in Phase 2.</p>
      </EuiCallOut>
    </>
  );
}
