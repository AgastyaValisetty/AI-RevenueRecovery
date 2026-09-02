import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: Parameters<typeof clsx>) {
  return twMerge(clsx(...inputs));
}

export const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export function clamp01(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}

export function formatPercent(value: number | null | undefined, decimals = 1): string {
  if (value == null || isNaN(value)) return '—';
  return `${(value * 100).toFixed(decimals)}%`;
}

export function formatCurrency(
  amount: number | string | null | undefined,
  _currency = 'INR',
  decimals = 0,
): string {
  if (amount == null) return '—';
  const num = typeof amount === 'string' ? parseFloat(amount) : amount;
  if (isNaN(num)) return '—';
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: _currency,
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(num);
}

export function formatCurrencyCompact(
  amount: number | string | null | undefined,
  _currency = 'INR',
): string {
  if (amount == null) return '—';
  const num = typeof amount === 'string' ? parseFloat(amount) : amount;
  if (isNaN(num)) return '—';

  const abs = Math.abs(num);
  let suffix = '';
  let value = num;

  if (abs >= 1e9) {
    value = num / 1e9;
    suffix = 'B';
  } else if (abs >= 1e6) {
    value = num / 1e6;
    suffix = 'M';
  } else if (abs >= 1e4) {
    value = num / 1e4;
    suffix = 'L';
  } else if (abs >= 1e3) {
    value = num / 1e3;
    suffix = 'K';
  }

  if (suffix) {
    return `₹${value.toFixed(value < 100 && abs >= 1e3 ? 1 : 2)}${suffix}`;
  }
  return `₹${num.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

export function formatNumber(value: number | string | null | undefined): string {
  if (value == null) return '—';
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return '—';
  return num.toLocaleString('en-IN');
}

export function formatDuration(
  hours: number | null | undefined,
  compact = false,
): string {
  if (hours == null || isNaN(hours)) return '—';
  const days = hours / 24;
  if (compact) {
    if (days >= 1) {
      return `${days.toFixed(1)}d`;
    }
    return `${hours.toFixed(1)}h`;
  }
  if (days >= 1) {
    const d = Math.floor(days);
    const h = Math.round((days - d) * 24);
    return `${d}d ${h}h`;
  }
  return `${hours.toFixed(1)}h`;
}

export function formatDate(date: string | Date, options: 'short' | 'medium' | 'long' = 'medium'): string {
  const d = typeof date === 'string' ? new Date(date) : date;
  if (isNaN(d.getTime())) return '—';

  switch (options) {
    case 'short':
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    case 'long':
      return d.toLocaleDateString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      });
    default:
      return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
  }
}

export function formatDateTime(date: string | Date): string {
  const d = typeof date === 'string' ? new Date(date) : date;
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatRelativeTime(date: string | Date): string {
  const d = typeof date === 'string' ? new Date(date) : date;
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHr / 24);

  if (diffSec < 60) return `${diffSec}s ago`;
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHr < 24) return `${diffHr}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return formatDate(d, 'short');
}

export function calculateRecoveryRate(recovered: number, total: number): number {
  if (total === 0) return 0;
  return recovered / total;
}

export function calculateWasteRate(wastedRetries: number, totalRetries: number): number {
  if (totalRetries === 0) return 0;
  return wastedRetries / totalRetries;
}

export function getProgressBarColor(rate: number): string {
  if (rate >= 0.9) return 'bg-green-400';
  if (rate >= 0.6) return 'bg-chartreuse';
  if (rate >= 0.3) return 'bg-warning';
  return 'bg-error';
}

export function getFailureCodeColor(code: string): string {
  const colors: Record<string, string> = {
    insufficient_funds: 'bg-blue-400',
    expired_card: 'bg-purple-400',
    incorrect_cvc: 'bg-orange-400',
    processing_error: 'bg-red-400',
    declined: 'bg-yellow-400',
    card_not_supported: 'bg-pink-400',
    call_issuer: 'bg-indigo-400',
    try_again: 'bg-teal-400',
  };
  return colors[code] || 'bg-gray-400';
}

export function getFailureCodeLabel(code: string): string {
  const labels: Record<string, string> = {
    insufficient_funds: 'Insufficient Funds',
    expired_card: 'Expired Card',
    incorrect_cvc: 'Incorrect CVC',
    processing_error: 'Processing Error',
    declined: 'Card Declined',
    card_not_supported: 'Card Not Supported',
    call_issuer: 'Call Issuer',
    try_again: 'Try Again',
  };
  return labels[code] || code.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
}

export function getPaymentMethodName(method: string): string {
  const names: Record<string, string> = {
    card: 'Card',
    bank_account: 'Bank Account',
    upi: 'UPI',
    wallet: 'Wallet',
    paypal: 'PayPal',
    apple_pay: 'Apple Pay',
    google_pay: 'Google Pay',
    crypto: 'Crypto',
  };
  return names[method] || method;
}

export function classVarianceAuthority<T extends Record<string, unknown>>(
  base: string,
  variants: Record<keyof T, Record<string, string>>,
) {
  return (props: { variant?: keyof T; className?: string }) => {
    const { variant = Object.keys(variants)[0] as keyof T, className } = props;
    const variantClass = variants[variant]?.[String(variant)] ?? '';
    return cn(base, variantClass, className);
  };
}

export function safeNumber(value: unknown, fallback = 0): number {
  if (typeof value === 'number') return isNaN(value) ? fallback : value;
  if (typeof value === 'string') {
    const parsed = parseFloat(value);
    return isNaN(parsed) ? fallback : parsed;
  }
  return fallback;
}

export function safeString(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value;
  if (value == null) return fallback;
  return String(value);
}

export function randomId(prefix = 'id'): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 11)}`;
}
