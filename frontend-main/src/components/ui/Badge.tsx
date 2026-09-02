import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

export type BadgeVariant =
  | 'default'
  | 'chartreuse'
  | 'money'
  | 'success'
  | 'warning'
  | 'error'
  | 'info'
  | 'outline';

export interface BadgeProps {
  variant?: BadgeVariant;
  size?: 'sm' | 'md';
  children: ReactNode;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-panel text-secondary border border-border-subtle',
  chartreuse: 'bg-chartreuse-bg text-chartreuse border border-chartreuse-border',
  money: 'bg-money-bg text-money border border-money-border',
  success: 'bg-success-bg text-success border border-success-border',
  warning: 'bg-warning-bg text-warning border border-warning-border',
  error: 'bg-error-bg text-error border border-error-border',
  info: 'bg-info-bg text-info border border-info-border',
  outline: 'text-tertiary border border-border-subtle',
};

const sizeStyles = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-xs font-medium',
};

export function Badge({
  variant = 'default',
  size = 'md',
  className,
  children,
}: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full font-medium',
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
    >
      {children}
    </span>
  );
}
