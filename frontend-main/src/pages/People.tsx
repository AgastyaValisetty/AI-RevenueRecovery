import { motion } from 'framer-motion';
import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users,
  Search,
  RefreshCw,
  User,
  Shield,
} from 'lucide-react';
import { usePeople } from '../hooks/useApi';
import { DataTable } from '../components/shared/DataTable';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Shimmer } from '../components/ui/Shimmer';
import { CountValue } from '../components/shared/MetricCard';
import type { Person } from '../lib/types';

export default function People() {
  const navigate = useNavigate();
  const { data: peopleData, loading } = usePeople({ limit: 100 });
  const [searchTerm, setSearchTerm] = useState('');

  const filteredPeople = useMemo(() => {
    if (!peopleData?.items) return [];
    if (!searchTerm) return peopleData.items;

    const lower = searchTerm.toLowerCase();
    return peopleData.items.filter(
      (p) =>
        p.name.toLowerCase().includes(lower) ||
        p.email.toLowerCase().includes(lower) ||
        p.person_id.toLowerCase().includes(lower),
    );
  }, [peopleData?.items, searchTerm]);

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
            People
          </h1>
          <p className="mt-1 text-sm text-tertiary">
            Customer profiles and recovery history.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-tertiary" />
            <input
              type="text"
              placeholder="Search people..."
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

      {/* ── Summary ── */}
      <PeopleSummary people={filteredPeople} loading={loading} />

      {/* ── Table ── */}
      <Card>
        <CardHeader>
          <CardTitle icon={<Users size={14} />}>
            Customer List ({filteredPeople.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <DataTable
            columns={[
              {
                key: 'name',
                header: 'Name',
                sortable: true,
                render: (row: Person) => (
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-chartreuse-bg text-chartreuse">
                      <User size={14} />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-primary">{row.name}</p>
                      <p className="text-xs text-tertiary">{row.email}</p>
                    </div>
                  </div>
                ),
              },
              {
                key: 'person_id',
                header: 'Person ID',
                render: (row: Person) => (
                  <span className="font-mono text-xs text-tertiary">
                    {row.person_id.slice(0, 8)}
                  </span>
                ),
              },
              {
                key: 'employment_status',
                header: 'Employment',
                sortable: true,
                render: (row: Person) => {
                  const label = row.employment_status.replace(/_/g, ' ');
                  return (
                    <Badge variant="outline" size="sm">
                      {label}
                    </Badge>
                  );
                },
              },
              {
                key: 'risk_tier',
                header: 'Risk Tier',
                sortable: true,
                render: (row: Person) => {
                  const variantMap: Record<string, 'success' | 'warning' | 'error' | 'info' | 'default'> = {
                    low: 'success',
                    medium: 'warning',
                    high: 'error',
                  };
                  return (
                    <Badge variant={variantMap[row.risk_tier] || 'default'} size="sm">
                      {row.risk_tier.toUpperCase()}
                    </Badge>
                  );
                },
              },
              {
                key: 'tags',
                header: 'Tags',
                render: (row: Person) => (
                  <div className="flex flex-wrap gap-1">
                    {row.tags?.slice(0, 3).map((tag) => (
                      <Badge key={tag} variant="outline" size="sm">
                        {tag}
                      </Badge>
                    ))}
                    {row.tags && row.tags.length > 3 && (
                      <Badge variant="outline" size="sm">
                        +{row.tags.length - 3}
                      </Badge>
                    )}
                  </div>
                ),
              },
              {
                key: 'created_at',
                header: 'Joined',
                sortable: true,
                render: (row: Person) => (
                  <span className="font-mono text-xs text-tertiary">
                    {new Date(row.created_at).toLocaleDateString('en-US', {
                      year: 'numeric',
                      month: 'short',
                      day: 'numeric',
                    })}
                  </span>
                ),
              },
            ]}
            data={filteredPeople}
            loading={loading}
            pagination={true}
            pageSize={25}
            onRowClick={(row: Person) => navigate(`/people/${row.person_id}`)}
            emptyMessage="No people found"
          />
        </CardContent>
      </Card>
    </motion.div>
  );
}

function PeopleSummary({
  people,
  loading,
}: {
  people: Person[];
  loading: boolean;
}) {
  const total = people.length;
  const riskTiers = useMemo(() => {
    return {
      low: people.filter((p) => p.risk_tier === 'low').length,
      medium: people.filter((p) => p.risk_tier === 'medium').length,
      high: people.filter((p) => p.risk_tier === 'high').length,
    };
  }, [people]);

  const summaryCards = [
    {
      title: 'Total Customers',
      value: <CountValue value={total} size="lg" />,
      icon: <Users size={20} />,
    },
    {
      title: 'Low Risk',
      value: <CountValue value={riskTiers.low} size="lg" />,
      icon: <Shield size={20} />,
    },
    {
      title: 'Medium Risk',
      value: <CountValue value={riskTiers.medium} size="lg" />,
      icon: <Shield size={20} />,
    },
    {
      title: 'High Risk',
      value: <CountValue value={riskTiers.high} size="lg" />,
      icon: <Shield size={20} />,
    },
  ];

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Shimmer key={i} className="h-20 rounded-xl" />
        ))}
      </div>
    );
  }

  return (
    <motion.div
      className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1 }}
    >
      {summaryCards.map((card) => (
        <motion.div key={card.title} whileHover={{ y: -2 }} transition={{ duration: 0.25 }}>
          <Card>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-tertiary">
                    {card.title}
                  </p>
                  <div className="mt-1">{card.value}</div>
                </div>
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-chartreuse-bg text-tertiary">
                  {card.icon}
                </div>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      ))}
    </motion.div>
  );
}
