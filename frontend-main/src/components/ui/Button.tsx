import { motion } from 'framer-motion';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { cn } from '../../lib/utils';

type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'destructive' | 'chartreuse';
type ButtonSize = 'sm' | 'md' | 'lg' | 'xl';

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  isLoading?: boolean;
  children?: ReactNode;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary:
    'bg-chartreuse text-bg-canvas border border-transparent hover:bg-chartreuse-dim shadow-chartreuse/20 hover:shadow-chartreuse/30 focus:ring-chartreuse',
  secondary:
    'bg-panel border border-border-subtle text-primary hover:bg-panel-hover focus:ring-chartreuse',
  outline:
    'border border-border-subtle text-tertiary hover:border-border-strong hover:text-primary focus:ring-chartreuse',
  ghost:
    'text-tertiary hover:bg-chartreuse-bg hover:text-chartreuse focus:ring-chartreuse',
  destructive:
    'bg-error text-bg-canvas border border-transparent hover:bg-error/80 focus:ring-error',
  chartreuse:
    'bg-chartreuse text-bg-canvas border border-transparent hover:bg-chartreuse-dim shadow-chartreuse/20 hover:shadow-chartreuse/30 focus:ring-chartreuse',
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-xs',
  md: 'h-10 px-4 text-sm',
  lg: 'h-12 px-5 text-sm font-medium',
  xl: 'h-14 px-6 text-base font-medium',
};

export function Button({
  variant = 'primary',
  size = 'md',
  icon,
  isLoading = false,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <motion.button
      whileTap={{ scale: 0.97 }}
      whileHover={{ scale: 1.02 }}
      transition={{ duration: 0.15, ease: 'easeOut' }}
      disabled={isLoading || disabled}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-full font-medium',
        'transition-all duration-250 ease-out',
        'focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-canvas',
        'disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100',
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
      {...(props as Record<string, unknown>)}
    >
      {isLoading ? (
        <svg
          className="-ml-1 h-4 w-4 animate-spin"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          aria-label="Loading"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H2c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      ) : icon ? (
        <span>{icon}</span>
      ) : null}
      {children}
    </motion.button>
  );
}
