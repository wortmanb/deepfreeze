/**
 * Minimal type stubs for @kbn/core/public.
 */

export interface CoreSetup {
  application: ApplicationSetup;
  getStartServices(): Promise<[CoreStart, any, any]>;
}

export interface CoreStart {}

export interface ApplicationSetup {
  register(app: AppRegistration): void;
}

export interface AppRegistration {
  id: string;
  title: string;
  mount: (params: AppMountParameters) => Promise<() => void> | (() => void);
}

export interface AppMountParameters {
  element: HTMLElement;
  history: ScopedHistory;
  appBasePath: string;
}

export interface ScopedHistory {
  location: { pathname: string };
  push(path: string): void;
  replace(path: string): void;
  listen(callback: (location: any, action: string) => void): () => void;
}

export interface Plugin<TSetup = void, TStart = void> {
  setup(core: CoreSetup): TSetup;
  start(core: CoreStart): TStart;
  stop?(): void;
}
