import React from 'react';
import ReactDOM from 'react-dom';
import { Router, Route, Switch } from 'react-router-dom';
import {
  EuiPageTemplate,
  EuiSideNav,
  EuiSpacer,
  EuiIcon,
} from '@elastic/eui';
import { AppMountParameters, CoreStart } from '@kbn/core/public';

import Overview from './pages/overview';
import Repositories from './pages/repositories';
import ThawRequests from './pages/thaw_requests';
import Actions from './pages/actions';
import Scheduler from './pages/scheduler';
import Activity from './pages/activity';

function DeepfreezeApp({ history, basename }: { history: AppMountParameters['history']; basename: string }) {
  const [isSideNavOpenOnMobile, setIsSideNavOpenOnMobile] = React.useState(false);

  // Determine current path for nav highlighting
  const currentPath = history.location.pathname;

  const sideNavItems = [
    {
      name: 'Deepfreeze',
      id: 'deepfreeze-nav',
      items: [
        {
          name: 'Overview',
          id: 'overview',
          icon: <EuiIcon type="dashboardApp" />,
          isSelected: currentPath === '/' || currentPath === '',
          onClick: () => history.push('/'),
        },
        {
          name: 'Repositories',
          id: 'repositories',
          icon: <EuiIcon type="database" />,
          isSelected: currentPath === '/repositories',
          onClick: () => history.push('/repositories'),
        },
        {
          name: 'Thaw Requests',
          id: 'thaw-requests',
          icon: <EuiIcon type="temperature" />,
          isSelected: currentPath === '/thaw-requests',
          onClick: () => history.push('/thaw-requests'),
        },
        {
          name: 'Actions',
          id: 'actions',
          icon: <EuiIcon type="play" />,
          isSelected: currentPath === '/actions',
          onClick: () => history.push('/actions'),
        },
        {
          name: 'Scheduler',
          id: 'scheduler',
          icon: <EuiIcon type="calendar" />,
          isSelected: currentPath === '/scheduler',
          onClick: () => history.push('/scheduler'),
        },
        {
          name: 'Activity',
          id: 'activity',
          icon: <EuiIcon type="clock" />,
          isSelected: currentPath === '/activity',
          onClick: () => history.push('/activity'),
        },
      ],
    },
  ];

  return (
    <Router history={history}>
      <EuiPageTemplate panelled restrictWidth={false}>
        <EuiPageTemplate.Sidebar sticky>
          <EuiSpacer size="s" />
          <EuiSideNav
            mobileTitle="Navigation"
            toggleOpenOnMobile={() => setIsSideNavOpenOnMobile(!isSideNavOpenOnMobile)}
            isOpenOnMobile={isSideNavOpenOnMobile}
            items={sideNavItems}
          />
        </EuiPageTemplate.Sidebar>
        <EuiPageTemplate.Section>
          <Switch>
            <Route exact path="/" component={Overview} />
            <Route path="/repositories" component={Repositories} />
            <Route path="/thaw-requests" component={ThawRequests} />
            <Route path="/actions" component={Actions} />
            <Route path="/scheduler" component={Scheduler} />
            <Route path="/activity" component={Activity} />
          </Switch>
        </EuiPageTemplate.Section>
      </EuiPageTemplate>
    </Router>
  );
}

export function renderApp(coreStart: CoreStart, { element, history, appBasePath }: AppMountParameters) {
  ReactDOM.render(
    <DeepfreezeApp history={history} basename={appBasePath} />,
    element,
  );

  // Return unmount callback
  return () => ReactDOM.unmountComponentAtNode(element);
}
