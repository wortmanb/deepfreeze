/**
 * Server-side HTTP client for communicating with the Deepfreeze service.
 *
 * All Kibana server routes proxy through this client. It handles:
 * - Base URL construction
 * - Auth token injection
 * - Error normalization
 * - Timeout handling
 */

import { Logger } from '@kbn/logging';

export interface ClientOptions {
  serviceUrl: string;
  serviceToken?: string;
  logger: Logger;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  path: string;
  body?: unknown;
  params?: Record<string, string | number | boolean>;
  timeout?: number;
}

export class DeepfreezeClient {
  private readonly baseUrl: string;
  private readonly token?: string;
  private readonly logger: Logger;

  constructor(options: ClientOptions) {
    // Strip trailing slash
    this.baseUrl = options.serviceUrl.replace(/\/$/, '');
    this.token = options.serviceToken;
    this.logger = options.logger;
  }

  async request<T = unknown>(options: RequestOptions): Promise<T> {
    const { method = 'GET', path, body, params, timeout = 30000 } = options;

    // Build URL with query params
    const url = new URL(path, this.baseUrl);
    if (params) {
      for (const [key, value] of Object.entries(params)) {
        url.searchParams.set(key, String(value));
      }
    }

    // Build headers
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    // Build fetch options
    const fetchOptions: RequestInit = {
      method,
      headers,
      signal: AbortSignal.timeout(timeout),
    };
    if (body !== undefined) {
      fetchOptions.body = JSON.stringify(body);
    }

    this.logger.debug(`${method} ${url.pathname}${url.search}`);

    try {
      const response = await fetch(url.toString(), fetchOptions);

      if (!response.ok) {
        const errorBody = await response.text();
        let parsed: unknown;
        try {
          parsed = JSON.parse(errorBody);
        } catch {
          parsed = { detail: errorBody };
        }
        this.logger.warn(`Deepfreeze service error: ${response.status} ${method} ${path}`);
        throw new DeepfreezeServiceError(
          response.status,
          `Deepfreeze service returned ${response.status}`,
          parsed,
        );
      }

      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof DeepfreezeServiceError) {
        throw error;
      }
      this.logger.error(`Failed to reach Deepfreeze service at ${this.baseUrl}: ${error}`);
      throw new DeepfreezeServiceError(
        502,
        `Cannot reach Deepfreeze service at ${this.baseUrl}`,
        { detail: String(error) },
      );
    }
  }

  // -- Convenience methods --

  async get<T = unknown>(path: string, params?: Record<string, string | number | boolean>): Promise<T> {
    return this.request<T>({ method: 'GET', path, params });
  }

  async post<T = unknown>(path: string, body?: unknown, params?: Record<string, string | number | boolean>): Promise<T> {
    return this.request<T>({ method: 'POST', path, body, params });
  }

  async put<T = unknown>(path: string, body?: unknown): Promise<T> {
    return this.request<T>({ method: 'PUT', path, body });
  }

  async del<T = unknown>(path: string): Promise<T> {
    return this.request<T>({ method: 'DELETE', path });
  }

  /**
   * Open an SSE connection to the Deepfreeze service.
   * Returns the raw Response for streaming.
   */
  async openEventStream(channel?: string): Promise<Response> {
    const url = new URL('/api/events', this.baseUrl);
    if (channel) {
      url.searchParams.set('channel', channel);
    }

    const headers: Record<string, string> = {
      Accept: 'text/event-stream',
    };
    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const response = await fetch(url.toString(), { headers });
    if (!response.ok) {
      throw new DeepfreezeServiceError(
        response.status,
        `Failed to open event stream: ${response.status}`,
      );
    }
    return response;
  }
}

export class DeepfreezeServiceError extends Error {
  constructor(
    public readonly statusCode: number,
    message: string,
    public readonly body?: unknown,
  ) {
    super(message);
    this.name = 'DeepfreezeServiceError';
  }
}
