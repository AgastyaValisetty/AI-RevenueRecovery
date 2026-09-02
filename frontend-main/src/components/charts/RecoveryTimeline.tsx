import { motion } from 'framer-motion';
import {
  formatCurrencyCompact,
  formatDateTime,
} from '../../lib/utils';
import type { SmartCase, RecoveryAction } from '../../lib/types';
import { StatusDot } from '../ui/StatusDot';

/**
 * RecoveryTimeline — signature timeline visualization.
 *
 * Renders a vertical timeline of recovery actions (or smart-case lifecycle
 * events) with precise typography, chartreuse progress, and money color
 * for recovered value milestones.
 */

export interface TimelineEvent {
  id: string;
  timestamp: string;
  label: string;
  description?: string;
  amount?: string;
  icon?: React.ReactNode;
  status: 'success' | 'pending' | 'failed' | 'info' | 'stopped';
  metadata?: Record<string, unknown>;
}

interface RecoveryTimelineProps {
  events: TimelineEvent[];
  orientation?: 'vertical' | 'horizontal';
  height?: number;
  showAxis?: boolean;
  compact?: boolean;
}

export function RecoveryTimeline({
  events,
  orientation = 'vertical',
  height = 400,
  showAxis = true,
  compact = false,
}: RecoveryTimelineProps) {
  const statusColors: Record<string, string> = {
    success: '#10B981',
    pending: '#F59E0B',
    failed: '#EF4444',
    info: '#38BDF8',
    stopped: '#6B6F6D',
  };

  const statusIcons: Record<string, string> = {
    success: '✓',
    pending: '⋯',
    failed: '×',
    info: '○',
    stopped: '||',
  };

  if (orientation === 'horizontal') {
    return (
      <div className="w-full overflow-x-auto">
        <div className="relative" style={{ height: 120 }}>
          {showAxis && (
            <motion.div
              className="absolute top-1/2 left-0 right-0 h-px bg-border-subtle"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            />
          )}
          <div className="relative flex h-full items-center justify-between">
            {events.map((event, index) => (
              <motion.div
                key={event.id}
                className="flex flex-col items-center"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.08, duration: 0.4 }}
              >
                <div
                  className="mb-2 flex h-8 w-8 items-center justify-center rounded-full border-2"
                  style={{
                    backgroundColor: 'var(--bg-canvas)',
                    borderColor: statusColors[event.status],
                    color: statusColors[event.status],
                  }}
                >
                  {event.icon || (
                    <span className="text-xs font-bold">{statusIcons[event.status]}</span>
                  )}
                </div>
                <div className="text-center">
                  <p className="text-xs font-medium text-primary">
                    {event.label}
                  </p>
                  <p className="text-xs text-tertiary">
                    {formatDateTime(event.timestamp)}
                  </p>
                  {event.amount && (
                    <p className="text-xs font-mono text-money">
                      {formatCurrencyCompact(parseFloat(event.amount))}
                    </p>
                  )}
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // Vertical (default)
  return (
    <div
      className="relative w-full overflow-y-auto"
      style={{ height }}
      role="list"
      aria-label="Recovery timeline"
    >
      {/* Vertical line */}
      {showAxis && (
        <motion.div
          className="absolute left-[19px] top-6 bottom-6 w-px bg-border-subtle"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 0.6 }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
        />
      )}

      <div className="relative">
        {events.map((event, index) => (
          <motion.div
            key={event.id}
            className="relative mb-6 ml-[20px] last:mb-0"
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: index * 0.06, duration: 0.4, ease: 'easeOut' }}
          >
            {/* Node */}
            <div
              className="absolute left-[-20px] top-0 flex h-8 w-8 items-center justify-center rounded-full border-2 bg-panel text-xs font-bold"
              style={{
                borderColor: statusColors[event.status],
                color: statusColors[event.status],
              }}
            >
              {event.icon
                ? event.icon
                : statusIcons[event.status]}
            </div>

            {/* Content card */}
            <motion.div
              className={cn(
                'rounded-xl border border-border-subtle bg-panel p-4',
                'transition-all duration-250',
                !compact && 'hover:border-border-strong hover:shadow-elevated',
              )}
              style={{
                borderLeft: `3px solid ${statusColors[event.status]}`,
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-primary">
                      {event.label}
                    </span>
                    {event.status === 'success' && event.amount && (
                      <span className="font-mono text-xs text-money">
                        {formatCurrencyCompact(parseFloat(event.amount))}
                      </span>
                    )}
                  </div>
                  {event.description && (
                    <p className="mt-1 text-xs text-tertiary">
                      {event.description}
                    </p>
                  )}
                  <p className="mt-1 text-xs font-mono text-tertiary">
                    {formatDateTime(event.timestamp)}
                  </p>
                </div>
                <StatusDot variant={event.status as any} size="sm" />
              </div>
            </motion.div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

function cn(...classes: (string | false | undefined)[]) {
  return classes.filter(Boolean).join(' ');
}

// ─── Smart-case timeline builder ───────────────────

export function useCaseTimeline(smartCase: SmartCase | null): TimelineEvent[] {
  if (!smartCase) return [];

  const events: TimelineEvent[] = [];

  // Add action history
  if (smartCase.prior_actions && smartCase.prior_actions.length > 0) {
    smartCase.prior_actions.forEach((action, i) => {
      events.push({
        id: `action-${i}`,
        timestamp: action.timestamp,
        label: action.action_type,
        description: `Retry #${i + 1}`,
        amount: action.amount ?? undefined,
        status: action.outcome === 'SUCCESS' ? 'success' : action.outcome === 'FAILED' ? 'failed' : 'pending',
      });
    });
  }

  // Add audit trail
  if (smartCase.audit_trail && smartCase.audit_trail.length > 0) {
    smartCase.audit_trail.forEach((entry) => {
      events.push({
        id: `audit-${entry.timestamp}-${entry.action}`,
        timestamp: entry.timestamp,
        label: entry.action,
        description: entry.detail,
        status: 'info',
        metadata: { actor: entry.actor },
      });
    });
  }

  // Add the scheduled action
  if (smartCase.scheduled_for) {
    events.push({
      id: 'scheduled',
      timestamp: smartCase.scheduled_for,
      label: smartCase.action_type,
      description: `Scheduled retry for case ${smartCase.case_id}`,
      status: 'pending',
    });
  }

  // Add executed action
  if (smartCase.executed_at) {
    events.push({
      id: 'executed',
      timestamp: smartCase.executed_at,
      label: smartCase.action_type,
      description: `Retry #${smartCase.retry_number}`,
      amount: smartCase.amount,
      status: smartCase.status === 'RECOVERED' ? 'success' : smartCase.status === 'STOPPED' ? 'stopped' : 'pending',
    });
  }

  return events.sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
}

// ─── Action timeline from recovery actions ─────────

export function useActionTimeline(actions: RecoveryAction[]): TimelineEvent[] {
  return actions
    .map((action) => ({
      id: action.action_id,
      timestamp: action.scheduled_for || action.created_at,
      label: action.action_type,
      description: action.failure_reason || action.reason || undefined,
      amount: action.amount || undefined,
      status: (action.outcome === 'SUCCESS' ? 'success' : action.outcome === 'FAILED' ? 'failed' : 'pending') as TimelineEvent['status'],
    }))
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
}

// ─── Simulation phase timeline ─────────────────────

export function useSimulationTimeline(state: {
  current_phase: string;
  events?: Array<{ timestamp: string; phase: string; message: string; severity: string }>;
}): TimelineEvent[] {
  if (!state.events) return [];

  return state.events.map((event) => ({
    id: event.timestamp + event.phase,
    timestamp: event.timestamp,
    label: event.phase,
    description: event.message,
    status: event.severity === 'error' ? 'failed' : event.severity === 'warning' ? 'pending' : 'info',
  }));
}
