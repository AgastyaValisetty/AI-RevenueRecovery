import React, { useState, useMemo } from 'react';
import { BookOpen, Search, ArrowDownLeft, ArrowUpRight, CheckCircle2, AlertTriangle, ChevronLeft, ChevronRight, Zap, Filter } from './ui/icons';
import { money } from '../utils/format';
import ScrollFade from './ui/ScrollFade';

export default function LedgerTable({ people, status, rawLedgerEntries, loading }) {
  const [search, setSearch] = useState('');
  const [eventTypeFilter, setEventTypeFilter] = useState('ALL');
  const [pageSize, setPageSize] = useState(250);
  const [currentPage, setCurrentPage] = useState(1);

  const entries = useMemo(() => {
    if (rawLedgerEntries && Array.isArray(rawLedgerEntries) && rawLedgerEntries.length > 0) {
      return rawLedgerEntries.map((e) => ({
        entry_id: e.entry_id,
        event_type: e.event_type,
        from_account: e.from_account_id ? `${e.from_account_id.slice(0, 8)}...` : 'System Bank Pool (RupeeBank)',
        to_account: e.to_account_id ? `${e.to_account_id.slice(0, 8)}...` : 'Merchant POS / Living Cost',
        amount: Number(e.amount),
        timestamp: e.simulation_timestamp ? e.simulation_timestamp.replace('T', ' ').slice(0, 19) + ' UTC' : '—',
        rawTimestamp: e.simulation_timestamp || '',
        metadata: e.metadata_json,
      }));
    }

    if (!people || people.length === 0) return [];

    const categories = ['groceries', 'utilities', 'dining', 'transport', 'entertainment'];
    const generated = [];

    // Fallback if backend has not returned ledger stream yet
    const currDate = status?.current_date || '2024-01-01';
    people.forEach((p, idx) => {
      generated.push({
        entry_id: `led_sal_${p.person_id.slice(0, 8)}`,
        event_type: 'SALARY_DEPOSIT',
        from_account: 'System Bank Pool (RupeeBank)',
        to_account: `${p.name} (Primary Account)`,
        amount: Number(p.salary),
        timestamp: `${currDate} 09:00:00 UTC`,
        rawTimestamp: currDate,
        metadata: { category: 'Monthly Payroll', type: 'Credit' },
      });

      const cat = categories[idx % categories.length];
      const dailySpend = Math.round(Number(p.salary) * (0.015 + (idx % 15) * 0.001));
      generated.push({
        entry_id: `led_liv_${p.person_id.slice(0, 8)}_d1`,
        event_type: 'LIVING_COST',
        from_account: `${p.name} (Primary Account)`,
        to_account: 'Merchant POS / Living Cost',
        amount: dailySpend,
        timestamp: `${currDate} 12:00:00 UTC`,
        rawTimestamp: currDate,
        metadata: { category: cat, day_type: 'weekday' },
      });
    });

    return generated;
  }, [people, rawLedgerEntries, status]);

  const filteredEntries = useMemo(() => {
    return entries.filter((e) => {
      const matchSearch =
        e.entry_id.toLowerCase().includes(search.toLowerCase()) ||
        e.from_account.toLowerCase().includes(search.toLowerCase()) ||
        e.to_account.toLowerCase().includes(search.toLowerCase()) ||
        (e.metadata?.category && String(e.metadata.category).toLowerCase().includes(search.toLowerCase()));
      const matchType = eventTypeFilter === 'ALL' || e.event_type === eventTypeFilter;
      return matchSearch && matchType;
    });
  }, [entries, search, eventTypeFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredEntries.length / pageSize));
  const paginated = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredEntries.slice(start, start + pageSize);
  }, [filteredEntries, currentPage, pageSize]);

  const getEventBadge = (type) => {
    switch (type) {
      case 'SALARY_DEPOSIT':
        return { label: 'Salary Deposit', className: 'tag-credit', icon: ArrowDownLeft };
      case 'LIVING_COST':
        return { label: 'Living Cost', className: 'tag-debit', icon: ArrowUpRight };
      case 'PAYMENT_SETTLED':
        return { label: 'Payment Settled', className: 'tag-subscription', icon: CheckCircle2 };
      case 'PAYMENT_FAILED':
        return { label: 'Payment Failed', className: 'tag-failed', icon: AlertTriangle };
      default:
        return { label: type, className: 'tag-default', icon: BookOpen };
    }
  };

  const handleSelectRecent250 = () => {
    setPageSize(250);
    setCurrentPage(1);
    setEventTypeFilter('ALL');
  };

  return (
    <ScrollFade className="animate-scroll-fade">
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <BookOpen size={18} />
            <span className="panel-title">Immutable Double-Entry Ledger</span>
            <span className="badge-count">
              {status?.ledger_entries ? `${status.ledger_entries} Database Records` : `${filteredEntries.length} Entries`}
            </span>
          </div>

          <div className="controls-bar">
            <button
              className={`btn ${pageSize === 250 ? 'btn-primary' : 'btn-outline'}`}
              onClick={handleSelectRecent250}
              title="View the 250 most recent records"
            >
              <Zap size={13} />
              <span>Most Recent 250</span>
            </button>

            <div className="search-input-wrapper">
              <Search size={15} />
              <input
                type="text"
                placeholder="Search account, ID, or category..."
                className="search-input"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setCurrentPage(1);
                }}
              />
            </div>

            <select
              className="select-filter"
              value={eventTypeFilter}
              onChange={(e) => {
                setEventTypeFilter(e.target.value);
                setCurrentPage(1);
              }}
            >
              <option value="ALL">All Event Types</option>
              <option value="SALARY_DEPOSIT">Salary Deposits</option>
              <option value="LIVING_COST">Living Costs</option>
              <option value="PAYMENT_SETTLED">Payment Settled</option>
              <option value="PAYMENT_FAILED">Payment Failed</option>
            </select>

            <select
              className="select-filter"
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setCurrentPage(1);
              }}
            >
              <option value={15}>15 per page</option>
              <option value={50}>50 per page</option>
              <option value={100}>100 per page</option>
              <option value={250}>250 per page (Recent 250)</option>
              <option value={500}>500 per page</option>
            </select>
          </div>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Entry ID</th>
                <th>Event Type</th>
                <th>From (Debit Account)</th>
                <th>To (Credit Account)</th>
                <th>Amount (₹)</th>
                <th>Simulation Timestamp</th>
                <th>Metadata</th>
              </tr>
            </thead>
            <tbody>
              {paginated.length === 0 ? (
                <tr>
                  <td colSpan="7">
                    <div className="empty-state">
                      <BookOpen size={32} />
                      <p>{loading ? 'Loading ledger entries...' : 'No ledger transactions recorded. Run a simulation day to generate activity.'}</p>
                    </div>
                  </td>
                </tr>
              ) : (
                paginated.map((entry) => {
                  const badge = getEventBadge(entry.event_type);
                  const BadgeIcon = badge.icon;
                  const isCredit = entry.event_type === 'SALARY_DEPOSIT';
                  return (
                    <tr key={entry.entry_id}>
                      <td className="mono-cell">{entry.entry_id.slice(0, 13)}...</td>
                      <td>
                        <span className={`tag-badge ${badge.className}`}>
                          <BadgeIcon size={12} />
                          <span>{badge.label}</span>
                        </span>
                      </td>
                      <td className="mono-cell">{entry.from_account}</td>
                      <td className="mono-cell">{entry.to_account}</td>
                      <td className={`currency ${isCredit ? 'currency-positive' : 'currency-negative'}`}>
                        {isCredit ? '+' : '-'}₹{money(entry.amount)}
                      </td>
                      <td className="mono-cell timestamp-cell">{entry.timestamp}</td>
                      <td>
                        {entry.metadata && (
                          <div className="metadata-tags">
                            {Object.entries(entry.metadata).map(([k, v]) => (
                              <span key={k} className="metadata-tag">{k}: {String(v)}</span>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {filteredEntries.length > 0 && (
          <div className="pagination">
            <div className="page-info">
              Showing {(currentPage - 1) * pageSize + 1} to{' '}
              {Math.min(currentPage * pageSize, filteredEntries.length)} of{' '}
              {filteredEntries.length} entries (Page size: {pageSize})
            </div>
            <div className="page-actions">
              <button
                className="btn btn-secondary"
                disabled={currentPage === 1}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              >
                <ChevronLeft size={14} />
              </button>
              <span className="page-number">
                {currentPage} / {totalPages}
              </span>
              <button
                className="btn btn-secondary"
                disabled={currentPage === totalPages}
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </ScrollFade>
  );
}
