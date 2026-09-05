import React, { useState, useMemo } from 'react';
import { BookOpen, Search, RefreshCw, Filter } from './ui/icons';
import ScrollFade from './ui/ScrollFade';
import "./TransactionsView.css";

const TransactionsView = ({ ledger, loading, onRefresh }) => {
  const [search, setSearch] = useState('');
  const [eventTypeFilter, setEventTypeFilter] = useState('ALL');
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 100;

  const eventTypes = useMemo(() => {
    if (!ledger || ledger.length === 0) return [];
    const set = new Set(ledger.map((e) => e.event_type));
    return Array.from(set).sort();
  }, [ledger]);

  const filteredLedger = useMemo(() => {
    if (!ledger) return [];
    return ledger.filter((e) => {
      const matchSearch =
        (e.event_type && e.event_type.toLowerCase().includes(search.toLowerCase())) ||
        (e.from_account_id && e.from_account_id.toLowerCase().includes(search.toLowerCase())) ||
        (e.to_account_id && e.to_account_id.toLowerCase().includes(search.toLowerCase()));
      const matchType =
        eventTypeFilter === 'ALL' || e.event_type === eventTypeFilter;
      return matchSearch && matchType;
    });
  }, [ledger, search, eventTypeFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredLedger.length / pageSize));
  const paginatedLedger = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredLedger.slice(start, start + pageSize);
  }, [filteredLedger, currentPage]);

  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= totalPages) {
      setCurrentPage(newPage);
    }
  };

  const getEventTypeClass = (type) => {
    switch (type) {
      case 'CREDIT':
      case 'SALARY_DEPOSIT':
        return 'tag-credit';
      case 'DEBIT':
      case 'LIVING_COST':
        return 'tag-debit';
      case 'SUBSCRIPTION':
        return 'tag-subscription';
      case 'PAYMENT_SETTLED':
        return 'tag-settled';
      case 'PAYMENT_FAILED':
        return 'tag-failed';
      default:
        return 'tag-default';
    }
  };

  return (
    <div className="transactions-view">
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <BookOpen size={18} />
              <span className="panel-title">Ledger Transactions</span>
              <span className="badge-count">{filteredLedger.length} Entries</span>
            </div>

            <div className="controls-bar">
              <div className="search-input-wrapper">
                <Search size={15} />
                <input
                  type="text"
                  placeholder="Search by event type or account…"
                  className="search-input"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setCurrentPage(1);
                  }}
                />
              </div>

              <div className="filter-group">
                <Filter size={14} />
                <select
                  className="select-filter"
                  value={eventTypeFilter}
                  onChange={(e) => {
                    setEventTypeFilter(e.target.value);
                    setCurrentPage(1);
                  }}
                >
                  <option value="ALL">All Event Types</option>
                  {eventTypes.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>

              <button
                className="btn btn-outline"
                onClick={onRefresh}
                disabled={loading}
                style={{ padding: '6px 14px', fontSize: '12px' }}
              >
                <RefreshCw size={12} className={loading ? 'spinner' : ''} />
                <span>Refresh</span>
              </button>
            </div>
          </div>

          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Event Type</th>
                  <th>From Account</th>
                  <th>To Account</th>
                  <th>Amount</th>
                  <th>Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {paginatedLedger.length === 0 ? (
                  <tr>
                    <td colSpan="5">
                      <div className="empty-state">
                        <BookOpen size={32} />
                        <p>{loading ? 'Loading transactions…' : 'No ledger entries. Run the simulation.'}</p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  paginatedLedger.map((entry, i) => (
                    <tr key={entry.entry_id || i}>
                      <td>
                        <span className={`tag-badge ${getEventTypeClass(entry.event_type)}`}>
                          {entry.event_type}
                        </span>
                      </td>
                      <td className="mono-cell">
                        {entry.from_account_id
                          ? `${entry.from_account_id.slice(0, 8)}…`
                          : '—'}
                      </td>
                      <td className="mono-cell">
                        {entry.to_account_id
                          ? `${entry.to_account_id.slice(0, 8)}…`
                          : '—'}
                      </td>
                      <td className="currency">
                        ₹{parseFloat(entry.amount || 0).toLocaleString()}
                      </td>
                      <td className="mono-cell" style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        {entry.simulation_timestamp
                          ? new Date(entry.simulation_timestamp).toLocaleString()
                          : '—'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {filteredLedger.length > 0 && (
            <div className="pagination">
              <div className="page-info">
                Showing {(currentPage - 1) * pageSize + 1} to{' '}
                {Math.min(currentPage * pageSize, filteredLedger.length)} of{' '}
                {filteredLedger.length} transactions
              </div>
              <div className="page-actions">
                <button
                  className="btn btn-secondary"
                  style={{ padding: '6px 12px' }}
                  disabled={currentPage === 1 || loading}
                  onClick={() => handlePageChange(currentPage - 1)}
                >
                  Previous
                </button>
                <span className="page-number">
                  {currentPage} / {totalPages}
                </span>
                <button
                  className="btn btn-secondary"
                  style={{ padding: '6px 12px' }}
                  disabled={currentPage === totalPages || loading}
                  onClick={() => handlePageChange(currentPage + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </ScrollFade>
    </div>
  );
};

export default TransactionsView;
