import { schema } from '@kbn/config-schema';
import { IRouter } from '@kbn/core/server';
import { DeepfreezeClient } from '../lib/deepfreeze_client';
import { API_BASE } from '../../common';

export function registerSchedulerRoutes(router: IRouter, client: DeepfreezeClient) {
  // List scheduled jobs
  router.get(
    { path: `${API_BASE}/scheduler/jobs`, validate: false },
    async (_context, _request, response) => {
      try {
        const result = await client.get('/api/scheduler/jobs');
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );

  // Add scheduled job
  router.post(
    {
      path: `${API_BASE}/scheduler/jobs`,
      validate: {
        body: schema.object({
          name: schema.string(),
          action: schema.string(),
          params: schema.recordOf(schema.string(), schema.any(), { defaultValue: {} }),
          cron: schema.maybe(schema.nullable(schema.string())),
          interval_seconds: schema.maybe(schema.nullable(schema.number())),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.post('/api/scheduler/jobs', request.body);
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );

  // Update scheduled job
  router.put(
    {
      path: `${API_BASE}/scheduler/jobs/{name}`,
      validate: {
        params: schema.object({ name: schema.string() }),
        body: schema.object({
          name: schema.string(),
          action: schema.string(),
          params: schema.recordOf(schema.string(), schema.any(), { defaultValue: {} }),
          cron: schema.maybe(schema.nullable(schema.string())),
          interval_seconds: schema.maybe(schema.nullable(schema.number())),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.put(
          `/api/scheduler/jobs/${request.params.name}`,
          request.body,
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

  // Delete scheduled job
  router.delete(
    {
      path: `${API_BASE}/scheduler/jobs/{name}`,
      validate: {
        params: schema.object({ name: schema.string() }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.del(`/api/scheduler/jobs/${request.params.name}`);
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );

  // Pause
  router.post(
    {
      path: `${API_BASE}/scheduler/jobs/{name}/pause`,
      validate: {
        params: schema.object({ name: schema.string() }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.post(`/api/scheduler/jobs/${request.params.name}/pause`);
        return response.ok({ body: result });
      } catch (error: any) {
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );

  // Resume
  router.post(
    {
      path: `${API_BASE}/scheduler/jobs/{name}/resume`,
      validate: {
        params: schema.object({ name: schema.string() }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.post(`/api/scheduler/jobs/${request.params.name}/resume`);
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
