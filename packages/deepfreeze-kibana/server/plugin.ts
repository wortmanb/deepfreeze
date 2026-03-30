import {
  CoreSetup,
  CoreStart,
  Logger,
  Plugin,
  PluginInitializerContext,
} from '@kbn/core/server';
import { DeepfreezeClient } from './lib/deepfreeze_client';
import { DeepfreezePluginConfig } from './config';
import { registerRoutes } from './routes';
import { PLUGIN_ID } from '../common';

export class DeepfreezeServerPlugin implements Plugin {
  private readonly logger: Logger;
  private readonly config: DeepfreezePluginConfig;

  constructor(initializerContext: PluginInitializerContext) {
    this.logger = initializerContext.logger.get();
    this.config = initializerContext.config.get<DeepfreezePluginConfig>();
  }

  public setup(core: CoreSetup) {
    this.logger.info(`Setting up ${PLUGIN_ID} plugin`);
    this.logger.info(`Deepfreeze service URL: ${this.config.serviceUrl}`);

    const client = new DeepfreezeClient({
      serviceUrl: this.config.serviceUrl,
      serviceToken: this.config.serviceToken,
      logger: this.logger,
    });

    const router = core.http.createRouter();
    registerRoutes(router, client, this.logger);

    this.logger.info(`${PLUGIN_ID} routes registered`);
    return {};
  }

  public start(_core: CoreStart) {
    this.logger.info(`${PLUGIN_ID} server plugin started`);
    return {};
  }

  public stop() {
    this.logger.info(`${PLUGIN_ID} server plugin stopped`);
  }
}
