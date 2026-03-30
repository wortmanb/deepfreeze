import { schema, TypeOf } from '@kbn/config-schema';

export const configSchema = schema.object({
  enabled: schema.boolean({ defaultValue: true }),
  serviceUrl: schema.string({ defaultValue: 'http://localhost:8000' }),
  serviceToken: schema.maybe(schema.string()),
});

export type DeepfreezePluginConfig = TypeOf<typeof configSchema>;
