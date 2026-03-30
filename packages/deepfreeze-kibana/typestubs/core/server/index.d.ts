/**
 * Minimal type stubs for @kbn/core/server.
 * These allow TypeScript compilation without the full Kibana source tree.
 * At runtime, Kibana provides the real implementations.
 */

export interface CoreSetup {
  http: HttpServiceSetup;
  getStartServices(): Promise<[CoreStart, any, any]>;
}

export interface CoreStart {}

export interface HttpServiceSetup {
  createRouter(): IRouter;
}

export interface IRouter {
  get(route: RouteConfig, handler: RequestHandler): void;
  post(route: RouteConfig, handler: RequestHandler): void;
  put(route: RouteConfig, handler: RequestHandler): void;
  delete(route: RouteConfig, handler: RequestHandler): void;
}

export interface RouteConfig {
  path: string;
  validate: any;
  options?: {
    xsrfRequired?: boolean;
    [key: string]: any;
  };
}

export type RequestHandler = (
  context: any,
  request: KibanaRequest,
  response: KibanaResponseFactory,
) => Promise<any>;

export interface KibanaRequest {
  params: any;
  query: any;
  body: any;
  headers: Record<string, string>;
}

export interface KibanaResponseFactory {
  ok(options?: { body?: any; headers?: Record<string, string> }): any;
  customError(options: { statusCode: number; body: { message: string } }): any;
}

export interface Plugin<TSetup = void, TStart = void> {
  setup(core: CoreSetup): TSetup;
  start(core: CoreStart): TStart;
  stop?(): void;
}

export interface PluginInitializerContext {
  logger: { get(): Logger };
  config: { get<T>(): T };
}

export interface Logger {
  info(message: string, ...args: any[]): void;
  warn(message: string, ...args: any[]): void;
  error(message: string, ...args: any[]): void;
  debug(message: string, ...args: any[]): void;
}
