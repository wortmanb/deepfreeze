import { IRouter, Logger } from '@kbn/core/server';
import { DeepfreezeClient } from '../lib/deepfreeze_client';
import { registerHealthRoutes } from './health';
import { registerStatusRoutes } from './status';
import { registerActionRoutes } from './actions';
import { registerJobRoutes } from './jobs';
import { registerSchedulerRoutes } from './scheduler';
import { registerEventRoutes } from './events';

export function registerRoutes(router: IRouter, client: DeepfreezeClient, logger: Logger) {
  registerHealthRoutes(router, client);
  registerStatusRoutes(router, client);
  registerActionRoutes(router, client);
  registerJobRoutes(router, client);
  registerSchedulerRoutes(router, client);
  registerEventRoutes(router, client, logger);
}
