import { motion } from 'framer-motion';
import { useMemo } from 'react';
import {
  Wallet,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  BarChart3,
} from 'lucide-react';
import { useLedgerEntries, useLedgerAccounts, useLedgerBalances } from '../hooks/useApi';
import { DataTable } from '../components/shared/DataTable';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Shimmer } from '../components/ui/Shimmer';
import { CurrencyValue, CountValue } from '../components/shared/MetricCard';
import { formatCurrency, formatDateTime } from '../lib/utils';
import type { LedgerEntry } from '../lib/types';

interface AccountBalance {
  name: string;
  balance: number;
}

export default function Ledger() {
  const { data: ledgerData, loading } = useLedgerEntries({ limit: 5000 });
  const { data: accounts } = useLedgerAccounts();
  const { data: balances } = useLedgerBalances();

  const accountsList = useMemo<AccountBalance[]>(() => {
    if (!accounts) return [];
    return accounts.map((a) => ({
      name: a.name,
      balance: a.balance,
    }));
  }, [accounts]);

  const entries = ledgerData?.items || [];

  const summaryStats = useMemo(() => {
    const totalDebits = entries.reduce((sum, e) => sum + e.debit, 0);
    const totalCredits = entries.reduce((sum, e) => sum + e.credit, 0);
    const net = totalCredits - totalDebits;

    return {
      totalDebits,
      totalCredits,
      net,
      entryCount: entries.length,
    };
  }, [entries]);

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
            Ledger
          </h1>
          <p className="mt-1 text-sm text-tertiary">
            Double-entry account records and balances.
          </p>
        </div>
        <Button variant="outline" size="sm" icon={<RefreshCw size={14} />}>
          Refresh
        </Button>
      </motion.div>

      {/* ── Balance Cards ── */}
      <BalanceCards accounts={accountsList} balances={balances} loading={loading} />

      {/* ── Summary Stats ── */}
      <SummaryStats stats={summaryStats} loading={loading} />

      {/* ── Transaction Table ── */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Wallet size={14} />}>
            Transaction Ledger ({entries.length} entries)
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <DataTable
            columns={[
              {
                key: 'timestamp',
                header: 'Timestamp',
                sortable: true,
                render: (row: LedgerEntry) => (
                  <span className="font-mono text-xs text-tertiary">
                    {formatDateTime(row.timestamp)}
                  </span>
                ),
              },
              {
                key: 'account',
                header: 'Account',
                sortable: true,
                render: (row: LedgerEntry) => (
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-chartreuse" />
                    <span className="font-mono text-xs text-primary">{row.account}</span>
                  </div>
                ),
              },
              {
                key: 'entry_type',
                header: 'Type',
                render: (row: LedgerEntry) => {
                  const isCredit = row.credit > 0;
                  return (
                    <Badge
                      variant={isCredit ? 'success' : 'error'}
                      size="sm"
                    >
                      {isCredit ? 'Credit' : 'Debit'}
                    </Badge>
                  );
                },
              },
              {
                key: 'description',
                header: 'Description',
                render: (row: LedgerEntry) => (
                  <span className="text-sm text-secondary max-w-xs truncate block">
                    {row.description}
                  </span>
                ),
              },
              {
                key: 'debit',
                header: 'Debit',
                render: (row: LedgerEntry) =>
                  row.debit > 0 ? (
                    <span className="font-mono text-sm text-error">
                      −{formatCurrency(row.debit)}
                    </span>
                  ) : (
                    <span className="text-tertiary">—</span>
                  ),
              },
              {
                key: 'credit',
                header: 'Credit',
                render: (row: LedgerEntry) =>
                  row.credit > 0 ? (
                    <span className="font-mono text-sm text-success">
                      +{formatCurrency(row.credit)}
                    </span>
                  ) : (
                    <span className="text-tertiary">—</span>
                  ),
              },
              {
                key: 'balance',
                header: 'Balance',
                render: (row: LedgerEntry) => (
                  <span className="font-mono text-sm text-primary">
                    {formatCurrency(row.balance)}
                  </span>
                ),
              },
            ]}
            data={entries}
            loading={loading}
            pagination={true}
            pageSize={25}
            emptyMessage="No ledger entries found"
          />
        </CardContent>
      </Card>
    </motion.div>
  );
}

function BalanceCards({
  accounts,
  balances,
  loading,
}: {
  accounts: AccountBalance[];
  balances: Record<string, number> | null;
  loading: boolean;
}) {
  const displayAccounts = accounts.length > 0 ? accounts :
    (balances ? Object.entries(balances).map(([name, balance]) => ({ name, balance })) : []);

  if (loading || displayAccounts.length === 0) {
    return (
      <motion.div
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        {Array.from({ length: 3 }).map((_, i) => (
          <Shimmer key={i} className="h-24 rounded-xl" />
        ))}
      </motion.div>
    );
  }

  return (
    <motion.div
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
    >
      {displayAccounts.map((account) => (
        <Card key={account.name} hover>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs uppercase tracking-wider text-tertiary">
                  {account.name}
                </p>
                <p className="mt-1 font-mono text-xl font-bold text-primary">
                  {formatCurrency(account.balance)}
                </p>
              </div>
              <div className={`p-2 rounded-lg ${account.balance >= 0 ? 'bg-success-bg text-success' : 'bg-error-bg text-error'}`}>
                {account.balance >= 0 ? <TrendingUp size={18} /> : <TrendingDown size={18} />}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </motion.div>
  );
}

function SummaryStats({
  stats,
  loading,
}: {
  stats: { totalDebits: number; totalCredits: number; net: number; entryCount: number };
  loading: boolean;
}) {
  const cards = [
    {
      title: 'Total Debits',
      value: <CurrencyValue amount={stats.totalDebits} size="lg" />,
      icon: <TrendingDown size={18} />,
      color: 'text-error',
    },
    {
      title: 'Total Credits',
      value: <CurrencyValue amount={stats.totalCredits} size="lg" />,
      icon: <TrendingUp size={18} />,
      color: 'text-success',
    },
    {
      title: 'Net Flow',
      value: <CurrencyValue amount={stats.net} size="lg" />,
      icon: <BarChart3 size={18} />,
      color: stats.net >= 0 ? 'text-success' : 'text-error',
    },
    {
      title: 'Total Entries',
      value: <CountValue value={stats.entryCount} size="lg" />,
      icon: <Wallet size={18} />,
      color: 'text-tertiary',
    },
  ];

  if (loading) {
    return (
      <motion.div
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        {Array.from({ length: 4 }).map((_, i) => (
          <Shimmer key={i} className="h-20 rounded-xl" />
        ))}
      </motion.div>
    );
  }

  return (
    <motion.div
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
    >
      {cards.map((card) => (
        <Card key={card.title}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                  {card.title}
                </p>
                <div className="mt-1">{card.value}</div>
              </div>
              <div className={`p-2 rounded-lg bg-chartreuse-bg ${card.color}`}>
                {card.icon}
              </div>
            </div>
          </CardContent>
        </Card>
      ))}
    </motion.div>
  );
}
