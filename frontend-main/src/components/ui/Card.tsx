import type { HTMLAttributes, ReactNode } from 'react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  hover?: boolean;
}

export function Card({ children, className, hover = false, ...props }: CardProps) {
  return (
    <motion.div
      className={cn(
        'rounded-xl border border-border-subtle bg-panel',
        'transition-all duration-250 ease-out',
        hover && 'group hover:border-border-strong hover:shadow-elevated',
        className,
      )}
      {...(props as Record<string, unknown>)}
    >
      {children}
    </motion.div>
  );
}

export interface CardHeaderProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function CardHeader({ children, className, ...props }: CardHeaderProps) {
  return (
    <div
      className={cn(
        'border-b border-border-subtle px-6 py-4',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export interface CardTitleProps extends HTMLAttributes<HTMLHeadingElement> {
  children: ReactNode;
  icon?: ReactNode;
}

export function CardTitle({ children, icon, className, ...props }: CardTitleProps) {
  return (
    <h3
      className={cn(
        'text-xs font-medium uppercase tracking-wider text-tertiary',
        className,
      )}
      {...props}
    >
      {icon && <span className="mr-2 inline-block">{icon}</span>}
      {children}
    </h3>
  );
}

export interface CardContentProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function CardContent({ children, className, ...props }: CardContentProps) {
  return (
    <div className={cn('p-6', className)} {...props}>
      {children}
    </div>
  );
}

export interface CardFooterProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function CardFooter({ children, className, ...props }: CardFooterProps) {
  return (
    <div
      className={cn(
        'border-t border-border-subtle px-6 py-4 text-sm text-tertiary',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}
