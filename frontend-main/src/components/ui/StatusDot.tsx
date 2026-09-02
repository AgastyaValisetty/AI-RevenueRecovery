import { cn } from '../../lib/utils';

export type StatusVariant =
  | 'online'
  | 'offline'
  | 'warning'
  | 'error'
  | 'idle'
  | 'pending'
  | 'success'
  | 'chartreuse'
  | 'money'
  | 'info'
  | 'default'
  | 'stopped'
  | 'failed'
  | 'healthy'
  | 'degraded'
  | 'operational'
  | 'active'
  | 'suspended'
  | 'closed';

interface StatusDotProps {
  variant?: StatusVariant;
  pulse?: boolean;
  size?: 'sm' | 'md' | 'lg';
  label?: string;
  className?: string;
}

const colors: Record<StatusVariant, string> = {
  online: 'bg-success',
  offline: 'bg-tertiary',
  warning: 'bg-warning',
  error: 'bg-error',
  idle: 'bg-tertiary',
  pending: 'bg-info',
  success: 'bg-success',
  chartreuse: 'bg-chartreuse',
  money: 'bg-money',
  info: 'bg-info',
  default: 'bg-tertiary',
  stopped: 'bg-warning',
  failed: 'bg-error',
  healthy: 'bg-success',
  degraded: 'bg-warning',
  operational: 'bg-success',
  active: 'bg-success',
  suspended: 'bg-warning',
  closed: 'bg-error',
};

const sizes = {
  sm: 'w-1.5 h-1.5',
  md: 'w-2 h-2',
  lg: 'w-3 h-3',
};

export function StatusDot({
  variant = 'online',
  pulse = false,
  size = 'md',
  label,
}: StatusDotProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5',
        'text-xs font-medium',
      )}
    >
      <span
        className={cn(
          'rounded-full',
          colors[variant],
          sizes[size],
          pulse && 'animate-pulse-subtle',
          pulse && 'shadow-glow-chartreuse',
        )}
      />
      {label && <span>{label}</span>}
    </span>
  );
}
