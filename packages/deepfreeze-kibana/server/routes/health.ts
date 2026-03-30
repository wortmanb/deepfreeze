import { IRouter } from '@kbn/core/server';
import { DeepfreezeClient } from '../lib/deepfreeze_client';
import { API_BASE } from '../../common';

export function registerHealthRoutes(router: IRouter, client: DeepfreezeClient) {
  router.get(
    { path: `${API_BASE}/health`, validate: false },
    async (_context, _request, response) => {
      try {
        const result = await client.get('/health');
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );

  router.get(
    { path: `${API_BASE}/ready`, validate: false },
    async (_context, _request, response) => {
      try {
        const result = await client.get('/ready');
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
