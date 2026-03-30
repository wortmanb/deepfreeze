import { AppMountParameters, CoreSetup, CoreStart, Plugin } from '@kbn/core/public';
import { PLUGIN_ID, PLUGIN_NAME } from '../common';

export class DeepfreezePublicPlugin implements Plugin {
  public setup(core: CoreSetup) {
    core.application.register({
      id: PLUGIN_ID,
      title: PLUGIN_NAME,
      // TODO: Add Kibana feature privilege check when security plugin is available
      async mount(params: AppMountParameters) {
        const { renderApp } = await import('./application');
        const [coreStart] = await core.getStartServices();
        return renderApp(coreStart, params);
      },
    });
    return {};
  }

  public start(_core: CoreStart) {
    return {};
  }

  public stop() {}
}
