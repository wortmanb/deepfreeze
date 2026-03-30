import { DeepfreezePublicPlugin } from './plugin';

export function plugin() {
  return new DeepfreezePublicPlugin();
}

export type { DeepfreezePublicPlugin as DeepfreezePublicPluginType };
