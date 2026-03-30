/**
 * Trim a date/datetime string to YYYY-MM-DDTHH:MM format.
 */
export function trimDate(val: unknown): string {
  if (!val) return '';
  let s = String(val);
  s = s.replace(/Z$/, '').replace(/[+-]\d{2}:\d{2}$/, '');
  if (s.length > 16) {
    s = s.substring(0, 16);
  }
  return s;
}
