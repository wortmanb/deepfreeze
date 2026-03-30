import { schema } from '@kbn/config-schema';
import { IRouter } from '@kbn/core/server';
import { DeepfreezeClient } from '../lib/deepfreeze_client';
import { API_BASE } from '../../common';

export function registerActionRoutes(router: IRouter, client: DeepfreezeClient) {
  // Rotate
  router.post(
    {
      path: `${API_BASE}/actions/rotate`,
      validate: {
        body: schema.object({
          year: schema.maybe(schema.number()),
          month: schema.maybe(schema.number()),
          keep: schema.maybe(schema.number()),
          dry_run: schema.boolean({ defaultValue: false }),
        }),
        query: schema.object({
          wait: schema.boolean({ defaultValue: true }),
          timeout: schema.number({ defaultValue: 120 }),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.post('/api/actions/rotate', request.body, {
          wait: request.query.wait,
          timeout: request.query.timeout,
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

  // Thaw create
  router.post(
    {
      path: `${API_BASE}/actions/thaw`,
      validate: {
        body: schema.object({
          start_date: schema.string(),
          end_date: schema.string(),
          duration: schema.number({ defaultValue: 7 }),
          tier: schema.string({ defaultValue: 'Standard' }),
          sync: schema.boolean({ defaultValue: false }),
          dry_run: schema.boolean({ defaultValue: false }),
        }),
        query: schema.object({
          wait: schema.boolean({ defaultValue: true }),
          timeout: schema.number({ defaultValue: 120 }),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.post('/api/actions/thaw', request.body, {
          wait: request.query.wait,
          timeout: request.query.timeout,
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

  // Thaw check
  router.post(
    {
      path: `${API_BASE}/actions/thaw/check`,
      validate: {
        body: schema.object({
          request_id: schema.maybe(schema.nullable(schema.string())),
        }),
        query: schema.object({
          wait: schema.boolean({ defaultValue: true }),
          timeout: schema.number({ defaultValue: 120 }),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.post('/api/actions/thaw/check', request.body, {
          wait: request.query.wait,
          timeout: request.query.timeout,
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

  // Refreeze
  router.post(
    {
      path: `${API_BASE}/actions/refreeze`,
      validate: {
        body: schema.object({
          request_id: schema.maybe(schema.nullable(schema.string())),
          dry_run: schema.boolean({ defaultValue: false }),
        }),
        query: schema.object({
          wait: schema.boolean({ defaultValue: true }),
          timeout: schema.number({ defaultValue: 120 }),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.post('/api/actions/refreeze', request.body, {
          wait: request.query.wait,
          timeout: request.query.timeout,
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

  // Cleanup
  router.post(
    {
      path: `${API_BASE}/actions/cleanup`,
      validate: {
        body: schema.object({
          refrozen_retention_days: schema.maybe(schema.nullable(schema.number())),
          dry_run: schema.boolean({ defaultValue: false }),
        }),
        query: schema.object({
          wait: schema.boolean({ defaultValue: true }),
          timeout: schema.number({ defaultValue: 120 }),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.post('/api/actions/cleanup', request.body, {
          wait: request.query.wait,
          timeout: request.query.timeout,
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

  // Repair
  router.post(
    {
      path: `${API_BASE}/actions/repair`,
      validate: {
        body: schema.object({
          dry_run: schema.boolean({ defaultValue: false }),
        }),
        query: schema.object({
          wait: schema.boolean({ defaultValue: true }),
          timeout: schema.number({ defaultValue: 120 }),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.post('/api/actions/repair', request.body, {
          wait: request.query.wait,
          timeout: request.query.timeout,
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

  // Setup (admin only)
  router.post(
    {
      path: `${API_BASE}/actions/setup`,
      validate: {
        body: schema.object({
          repo_name_prefix: schema.string({ defaultValue: 'deepfreeze' }),
          bucket_name_prefix: schema.string({ defaultValue: 'deepfreeze' }),
          ilm_policy_name: schema.maybe(schema.nullable(schema.string())),
          index_template_name: schema.maybe(schema.nullable(schema.string())),
          dry_run: schema.boolean({ defaultValue: false }),
        }),
        query: schema.object({
          wait: schema.boolean({ defaultValue: true }),
          timeout: schema.number({ defaultValue: 120 }),
        }),
      },
    },
    async (_context, request, response) => {
      try {
        const result = await client.post('/api/actions/setup', request.body, {
          wait: request.query.wait,
          timeout: request.query.timeout,
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
}
