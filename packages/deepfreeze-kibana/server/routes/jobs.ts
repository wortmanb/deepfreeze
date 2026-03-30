import { schema } from '@kbn/config-schema';
import { IRouter } from '@kbn/core/server';
import { DeepfreezeClient } from '../lib/deepfreeze_client';
import { API_BASE } from '../../common';

export function registerJobRoutes(router: IRouter, client: DeepfreezeClient) {
  // List jobs
  router.get(
    {
      path: `${API_BASE}/jobs`,
      validate: {
        query: schema.object({
          status: schema.maybe(schema.string()),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const params: Record<string, string> = {};
        if (request.query.status) {
          params.status = request.query.status;
        }
        const result = await client.get('/api/jobs', params);
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );

  // Get job by ID
  router.get(
    {
      path: `${API_BASE}/jobs/{jobId}`,
      validate: {
        params: schema.object({ jobId: schema.string() }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.get(`/api/jobs/${request.params.jobId}`);
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );

  // Cancel job
  router.delete(
    {
      path: `${API_BASE}/jobs/{jobId}`,
      validate: {
        params: schema.object({ jobId: schema.string() }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.del(`/api/jobs/${request.params.jobId}`);
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
