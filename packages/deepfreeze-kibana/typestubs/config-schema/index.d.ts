/**
 * Minimal type stubs for @kbn/config-schema.
 */

export type TypeOf<T> = any;

export interface SchemaType {
  boolean(options?: { defaultValue?: boolean }): any;
  string(options?: { defaultValue?: string }): any;
  number(options?: { defaultValue?: number }): any;
  object(schema: Record<string, any>): any;
  maybe(type: any): any;
  nullable(type: any): any;
  recordOf(keyType: any, valueType: any, options?: any): any;
  any(): any;
}

export const schema: SchemaType;
