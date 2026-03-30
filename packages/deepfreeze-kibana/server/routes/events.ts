import { schema } from '@kbn/config-schema';
import { IRouter, Logger } from '@kbn/core/server';
import { DeepfreezeClient } from '../lib/deepfreeze_client';
import { API_BASE } from '../../common';

/**
 * SSE relay — proxies the Deepfreeze event stream through Kibana
 * so the browser never needs direct access to the Deepfreeze service.
 */
export function registerEventRoutes(router: IRouter, client: DeepfreezeClient, logger: Logger) {
  router.get(
    {
      path: `${API_BASE}/events`,
      validate: {
        query: schema.object({
          channel: schema.maybe(schema.string()),
        }),
      },
      options: {
        // EventSource can't send custom headers, so we exempt this
        // route from XSRF protection. It's a read-only GET endpoint.
        xsrfRequired: false,
      },
    },
    async (_context, request, response) => {
      try {
        const upstreamResponse = await client.openEventStream(request.query.channel);

        if (!upstreamResponse.body) {
          return response.customError({
            statusCode: 502,
            body: { message: 'No event stream body from Deepfreeze service' },
          });
        }

        // Return a streaming response
        // NOTE: The exact Kibana API for streaming responses varies by version.
        // In Kibana 8.x, we return a custom response with the stream body.
        // This may need adaptation for specific Kibana builds.
        return response.ok({
          headers: {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            Connection: 'keep-alive',
          },
          // @ts-expect-error — Kibana's response typing doesn't fully support streams;
          // the underlying hapi server handles ReadableStream bodies correctly.
          body: upstreamResponse.body,
        });
      } catch (error: any) {
        logger.warn(`SSE relay failed: ${error.message}`);
        return response.customError({
          statusCode: error.statusCode || 502,
          body: { message: error.message },
        });
      }
    },
  );
}
