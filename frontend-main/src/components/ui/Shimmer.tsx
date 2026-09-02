import type { ReactNode } from 'react';
import { cn } from '../../lib/utils';

interface ShimmerProps {
  children?: ReactNode;
  className?: string;
  dark?: boolean;
}

/** Loading skeleton wrapper — applies shimmer animation. */
export function Shimmer({ children, className, dark }: ShimmerProps) {
  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-md bg-panel',
        'before:absolute before:inset-0',
        'before:bg-gradient-to-r before:from-transparent',
        'before:via-white/3 before:to-transparent',
        'before:animate-[shimmer_1.8s_ease-in-out_infinite]',
        dark && 'before:via-white/5',
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Simple skeleton bars — pass width classes. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        'rounded bg-border-subtle',
        className,
      )}
    />
  );
}

/** Skeleton block for text lines. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn(
            'h-3 bg-border-subtle',
            i === lines - 1 ? 'w-2/3' : 'w-full',
          )}
        />
      ))}
    </div>
  );
}
