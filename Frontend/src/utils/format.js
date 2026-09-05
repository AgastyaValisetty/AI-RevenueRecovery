/**
 * Shared formatting utilities for currency, percentages, and numbers.
 * Centralised so every component renders values consistently.
 */

export const money = (value) =>
  `₹${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export const formatCurrency = (value) =>
  `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

/**
 * Format a fraction (0..1) as a percentage string ("83.0%").
 * Accepts an optional `total` for the legacy (value, total) signature used
 * in a few analytics views — when `total` is provided we render value/total.
 */
export const pct = (value, total) => {
  const v = Number(value);
  if (total != null && Number(total)) {
    return `${((v / Number(total)) * 100).toFixed(1)}%`;
  }
  if (!Number.isFinite(v)) return '0.0%';
  return `${(v * 100).toFixed(1)}%`;
};

/**
 * Alias kept for clarity in callers that already have a percentage in
 * 0..100 form (e.g. aggregate metrics returned by /api/.../metrics).
 */
export const formatPct = (value) => {
  const v = Number(value);
  if (!Number.isFinite(v)) return '0.0%';
  return `${v.toFixed(1)}%`;
};
