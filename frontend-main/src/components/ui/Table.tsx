import { type HTMLAttributes, type ReactNode, forwardRef } from 'react';
import { cn } from '../../lib/utils';

export interface TableProps extends HTMLAttributes<HTMLTableElement> {
  children: ReactNode;
  stickyHeader?: boolean;
}

export const Table = forwardRef<HTMLTableElement, TableProps>(
  ({ children, className, stickyHeader = true, ...props }, ref) => (
    <div className="relative w-full overflow-x-auto">
      <table
        ref={ref}
        className={cn(
          'w-full border-collapse text-sm text-tertiary',
          '[&>*_*[hidden]]:display-none',
          className,
        )}
        {...props}
      >
        <thead
          className={cn(
            'sticky top-0 z-10 bg-elevated/80 backdrop-blur-xs',
            'border-b border-border-subtle',
            !stickyHeader && 'sticky top-0',
          )}
        >
          {children}
        </thead>
        {children}
      </table>
    </div>
  ),
);
Table.displayName = 'Table';

export function TableHeader({ children, className, ...props }: HTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        'px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-tertiary',
        className,
      )}
      {...props}
    >
      {children}
    </th>
  );
}

export function TableCell({ children, className, ...props }: HTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn(
        'px-4 py-3 align-middle transition-colors',
        className,
      )}
      {...props}
    >
      {children}
    </td>
  );
}

// ── Simple table wrapper ─────────────────────────
export interface SimpleTableProps {
  columns: {
    key: string;
    header: string;
    className?: string;
    render?: (row: unknown) => ReactNode;
  }[];
  data: unknown[];
  onRowClick?: (row: unknown) => void;
  className?: string;
}
