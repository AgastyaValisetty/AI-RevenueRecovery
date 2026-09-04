/**
 * Shared formatting utilities for currency, percentages, and numbers.
 * Centralised so every component renders values consistently.
 */

export const money = (value) =>
  `₹${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

export const formatCurrency = (value) =>
  `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

export const pct = (value, total) =>
  total ? `${((Number(value) / Number(total)) * 100).toFixed(1)}%` : '0.0%';

export const formatPct = (value) =>
  `${Number(value || 0).toFixed(1)}%`;
