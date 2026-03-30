import { PluginInitializerContext } from '@kbn/core/server';
import { configSchema } from './config';
import { DeepfreezeServerPlugin } from './plugin';

export const config = {
  schema: configSchema,
};

export function plugin(initializerContext: PluginInitializerContext) {
  return new DeepfreezeServerPlugin(initializerContext);
}

export type { DeepfreezeServerPlugin as DeepfreezeServerPluginType };
