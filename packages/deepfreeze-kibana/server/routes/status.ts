import { schema } from '@kbn/config-schema';
import { IRouter } from '@kbn/core/server';
import { DeepfreezeClient } from '../lib/deepfreeze_client';
import { API_BASE } from '../../common';

export function registerStatusRoutes(router: IRouter, client: DeepfreezeClient) {
  // Full status
  router.get(
    {
      path: `${API_BASE}/status`,
      validate: {
        query: schema.object({
          force_refresh: schema.boolean({ defaultValue: false }),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.get('/api/status', {
          force_refresh: request.query.force_refresh,
        });
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );

  // Sub-resources
  for (const sub of ['cluster', 'repositories', 'thaw-requests', 'buckets', 'ilm-policies']) {
    router.get(
      { path: `${API_BASE}/status/${sub}`, validate: false },
      async (_context, _request, response) => {
        try {
          const result = await client.get(`/api/status/${sub}`);
          return response.ok({ body: result });
        } catch (error: any) {
          return response.customError({
            statusCode: error.statusCode || 502,
            body: { message: error.message },
          });
        }
      },
    );
  }

  // Restore progress
  router.get(
    {
      path: `${API_BASE}/thaw-requests/{requestId}/restore-progress`,
      validate: {
        params: schema.object({ requestId: schema.string() }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.get(
          `/api/thaw-requests/${request.params.requestId}/restore-progress`,
        );
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );

  // History
  router.get(
    {
      path: `${API_BASE}/history`,
      validate: {
        query: schema.object({
          limit: schema.number({ defaultValue: 25 }),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.get('/api/history', { limit: request.query.limit });
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );

  // Audit log
  router.get(
    {
      path: `${API_BASE}/audit`,
      validate: {
        query: schema.object({
          limit: schema.number({ defaultValue: 50 }),
          action: schema.maybe(schema.string()),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const params: Record<string, string | number> = { limit: request.query.limit };
        if (request.query.action) {
          params.action = request.query.action;
        }
        const result = await client.get('/api/audit', params);
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );
}
