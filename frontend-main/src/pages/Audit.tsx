import { motion } from 'framer-motion';
import { useState, useMemo } from 'react';
import {
  FileText,
  Search,
  RefreshCw,
  User,
} from 'lucide-react';
import { useAuditLogs } from '../hooks/useApi';
import { DataTable } from '../components/shared/DataTable';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Shimmer } from '../components/ui/Shimmer';
import { formatDateTime } from '../lib/utils';

interface AuditLog {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  detail: string;
  severity: 'info' | 'warning' | 'error';
}

// Since we don't have a dedicated audit API, we'll simulate from simulation events
// The backend has /api/simulation/status which includes events

export default function Audit() {
  const { data: simState, loading, refetch: _refetch } = useAuditLogs();
  const [searchTerm, setSearchTerm] = useState('');

  const allEntries: AuditLog[] = useMemo(() => {
    if (!simState?.events) return [];
    return simState.events.map((event, i) => ({
      id: `event-${i}`,
      timestamp: event.timestamp,
      actor: event.phase,
      action: event.severity,
      detail: event.message,
      severity: event.severity as 'info' | 'warning' | 'error',
    }));
  }, [simState?.events]);

  const filteredEntries = useMemo(() => {
    if (!searchTerm) return allEntries;
    const lower = searchTerm.toLowerCase();
    return allEntries.filter(
      (entry) =>
        entry.actor.toLowerCase().includes(lower) ||
        entry.action.toLowerCase().includes(lower) ||
        entry.detail.toLowerCase().includes(lower),
    );
  }, [allEntries, searchTerm]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: 'easeOut' }}
      className="space-y-6"
    >
      {/* ── Header ── */}
      <motion.div
        className="flex items-center justify-between"
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div>
          <h1 className="font-display text-3xl font-bold text-primary tracking-tighter">
            Audit Log
          </h1>
          <p className="mt-1 text-sm text-tertiary">
            System-wide event log and policy decision trail.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-tertiary" />
            <input
              type="text"
              placeholder="Search logs..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="rounded-lg border border-border-subtle bg-elevated px-4 py-2 pl-10 text-sm text-primary placeholder-tertiary focus:border-chartreuse focus:outline-none focus:ring-1 focus:ring-chartreuse"
            />
          </div>
          <Button variant="outline" size="sm" icon={<RefreshCw size={14} />}>
            Refresh
          </Button>
        </div>
      </motion.div>

      {/* ── Statistics ── */}
      <AuditStats entries={allEntries} />

      {/* ── Table ── */}
      <AuditTable entries={filteredEntries} loading={loading} />
    </motion.div>
  );
}

function AuditStats({ entries }: { entries: AuditLog[] }) {
  const totalCount = entries.length;
  const errorCount = entries.filter((e) => e.severity === 'error').length;
  const warningCount = entries.filter((e) => e.severity === 'warning').length;
  const infoCount = entries.filter((e) => e.severity === 'info').length;

  const cards = [
    { title: 'Total Events', value: totalCount, color: 'text-tertiary' },
    { title: 'Errors', value: errorCount, color: 'text-error' },
    { title: 'Warnings', value: warningCount, color: 'text-warning' },
    { title: 'Info', value: infoCount, color: 'text-info' },
  ];

  return (
    <motion.div
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
    >
      {cards.map((card) => (
        <Card key={card.title}>
          <CardContent className="p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
              {card.title}
            </p>
            <p className={`mt-1 font-mono text-2xl font-bold ${card.color}`}>
              {card.value.toLocaleString()}
            </p>
          </CardContent>
        </Card>
      ))}
    </motion.div>
  );
}

function AuditTable({
  entries,
  loading,
}: {
  entries: AuditLog[];
  loading: boolean;
}) {
  const columns = [
    {
      key: 'timestamp',
      header: 'Timestamp',
      sortable: true,
      render: (row: AuditLog) => (
        <span className="font-mono text-xs text-tertiary">
          {formatDateTime(row.timestamp)}
        </span>
      ),
    },
    {
      key: 'actor',
      header: 'Actor',
      sortable: true,
      render: (row: AuditLog) => (
        <div className="flex items-center gap-2">
          <User size={14} className="text-tertiary" />
          <span className="text-sm text-primary">{row.actor}</span>
        </div>
      ),
    },
    {
      key: 'action',
      header: 'Action',
      sortable: true,
      render: (row: AuditLog) => (
        <Badge variant={severityVariant(row.severity)} size="sm">
          {row.action}
        </Badge>
      ),
    },
    {
      key: 'detail',
      header: 'Detail',
      render: (row: AuditLog) => (
        <span className="text-sm text-secondary max-w-xs truncate block">
          {row.detail}
        </span>
      ),
    },
    {
      key: 'severity',
      header: 'Severity',
      render: (row: AuditLog) => (
        <Badge variant={severityVariant(row.severity)} size="sm">
          {row.severity.toUpperCase()}
        </Badge>
      ),
    },
  ];

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Event Log</CardTitle>
        </CardHeader>
        <CardContent>
          <Shimmer className="h-64 w-full rounded" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle icon={<FileText size={14} />}>
          Event Log ({entries.length} events)
        </CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <DataTable
          columns={columns as any}
          data={entries}
          loading={false}
          pagination={true}
          pageSize={25}
          emptyMessage="No audit events found"
        />
      </CardContent>
    </Card>
  );
}

function severityVariant(severity: string): 'error' | 'warning' | 'info' | 'default' {
  switch (severity) {
    case 'error': return 'error';
    case 'warning': return 'warning';
    case 'info': return 'info';
    default: return 'default';
  }
}
