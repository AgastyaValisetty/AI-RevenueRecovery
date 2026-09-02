import { motion } from 'framer-motion';
import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';
import { Badge } from '../ui/Badge';

export interface MetricCardProps {
  title: string;
  value: ReactNode;
  subtitle?: string;
  icon?: ReactNode;
  trend?: 'up' | 'down' | 'neutral' | 'none';
  trendValue?: string;
  variant?: 'default' | 'chartreuse' | 'money' | 'panel' | 'warning';
  className?: string;
}

const variantStyles = {
  default: {
    bg: 'bg-panel',
    border: 'border-border-subtle',
    valueColor: 'text-primary',
    accent: 'text-tertiary',
  },
  chartreuse: {
    bg: 'bg-panel',
    border: 'border-chartreuse-border',
    valueColor: 'text-chartreuse',
    accent: 'text-chartreuse-dim',
  },
  money: {
    bg: 'bg-panel',
    border: 'border-money-border',
    valueColor: 'text-money',
    accent: 'text-money-dim',
  },
  panel: {
    bg: 'bg-elevated',
    border: 'border-border-subtle',
    valueColor: 'text-primary',
    accent: 'text-tertiary',
  },
  warning: {
    bg: 'bg-panel',
    border: 'border-warning-border',
    valueColor: 'text-warning',
    accent: 'text-warning-dim',
  },
};

export function MetricCard({
  title,
  value,
  subtitle,
  icon,
  trend = 'none',
  trendValue,
  variant = 'default',
  className,
}: MetricCardProps) {
  const v = variantStyles[variant];

  const trendIcon = {
    up: '↗',
    down: '↘',
    neutral: '→',
    none: '',
  }[trend];

  const trendColor = trend === 'up' ? 'text-success' : trend === 'down' ? 'text-error' : 'text-tertiary';

  return (
    <motion.div
      whileHover={{ y: -2 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className={cn(
        'group rounded-xl border p-6',
        'transition-all duration-250',
        v.bg,
        v.border,
        'hover:shadow-elevated',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
            {title}
          </p>
          <div className="mt-2 text-3xl font-bold text-display tracking-tight" style={{ color: 'var(--tw-text-opacity)' }}>
            {value}
          </div>
          {subtitle && (
            <p className="mt-1 text-xs text-tertiary">{subtitle}</p>
          )}
          {trendValue && (
            <p className={cn('mt-1 text-xs font-medium', trendColor)}>
              {trendIcon} {trendValue}
            </p>
          )}
        </div>
        {icon && (
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-tertiary group-hover:text-chartreuse transition-colors"
            style={{ background: 'rgba(201, 243, 91, 0.05)' }}
          >
            {icon}
          </div>
        )}
      </div>
    </motion.div>
  );
}

// ── Value renderers ────────────────────────────────

export function CurrencyValue({
  amount,
  currency: _currency = 'INR',
  size = 'lg',
  prefix = true,
  compact = false,
}: {
  amount: number | string | null;
  currency?: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  prefix?: boolean;
  compact?: boolean;
}) {
  if (amount == null) return <span className="text-tertiary">—</span>;
  const num = typeof amount === 'string' ? parseFloat(amount) : amount;

  if (isNaN(num)) return <span className="text-tertiary">—</span>;

  let formatted: string;
  if (compact) {
    const abs = Math.abs(num);
    if (abs >= 1e8) {
      formatted = `₹${(num / 1e8).toFixed(2)}Cr`;
    } else if (abs >= 1e6) {
      formatted = `₹${(num / 1e6).toFixed(2)}M`;
    } else if (abs >= 1e4) {
      formatted = `₹${(num / 1e3).toFixed(1)}K`;
    } else {
      formatted = `₹${num.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
    }
  } else {
    formatted = `₹${num.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 0 })}`;
  }

  const sizeClass = {
    sm: 'text-lg',
    md: 'text-xl',
    lg: 'text-3xl',
    xl: 'text-5xl',
  }[size];

  return <span className={cn('font-mono font-bold text-money', sizeClass)}>{prefix ? formatted : formatted.slice(1)}</span>;
}

export function PercentValue({
  value,
  size = 'lg',
  delta = false,
}: {
  value: number | null;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  delta?: boolean;
}) {
  if (value == null || isNaN(value)) return <span className="text-tertiary">—</span>;

  const sizeClass = {
    sm: 'text-lg',
    md: 'text-xl',
    lg: 'text-3xl',
    xl: 'text-5xl',
  }[size];

  const colorClass = delta
    ? value >= 0
      ? 'text-success'
      : 'text-error'
    : 'text-primary';

  const sign = delta && value > 0 ? '+' : '';

  return (
    <span className={cn('font-mono font-bold', sizeClass, colorClass)}>
      {sign}{value.toFixed(1)}%
    </span>
  );
}

export function CountValue({
  value,
  size = 'lg',
  prefix = '',
  color = 'text-primary',
}: {
  value: number | null;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  prefix?: string;
  color?: string;
}) {
  if (value == null || isNaN(value)) return <span className="text-tertiary">—</span>;

  const sizeClass = {
    sm: 'text-lg',
    md: 'text-xl',
    lg: 'text-3xl',
    xl: 'text-5xl',
  }[size];

  return (
    <span className={cn('font-mono font-bold', sizeClass, color)}>
      {prefix}{value.toLocaleString('en-IN')}
    </span>
  );
}

export function StatusBadge({
  status,
  size = 'md',
}: {
  status: string;
  size?: 'sm' | 'md';
}) {
  const variantMap: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
    COMPLETED: 'success',
    RUNNING: 'info',
    PENDING: 'warning',
    FAILED: 'error',
    IDLE: 'default',
    RECOVERED: 'success',
    STOPPED: 'warning',
    QUEUED: 'default',
    IN_PROGRESS: 'info',
    EXPIRED: 'warning',
    healthy: 'success',
    degraded: 'warning',
    outage: 'error',
    operational: 'success',
    active: 'success',
    suspended: 'warning',
    closed: 'error',
  };

  const variant = variantMap[status] || 'default';
  const label = status.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());

  return (
    <Badge variant={variant} size={size}>
      {label}
    </Badge>
  );
}
