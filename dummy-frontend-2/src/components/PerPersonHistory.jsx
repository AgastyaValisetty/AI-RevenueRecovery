import React, { useState, useMemo } from "react";
import { History, Search, RefreshCw } from "./ui/icons";
import ScrollFade from "./ui/ScrollFade";
import "./PerPersonHistory.css";

const PerPersonHistory = ({ ledger, loading, onRefresh }) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedAccountId, setSelectedAccountId] = useState("");

  // Get unique account IDs from ledger
  const allAccountIds = useMemo(() => {
    if (!ledger) return [];
    const ids = new Set();
    ledger.forEach((entry) => {
      if (entry.from_account_id) ids.add(entry.from_account_id);
      if (entry.to_account_id) ids.add(entry.to_account_id);
    });
    return Array.from(ids).sort();
  }, [ledger]);

  // Filter history by account ID or search term
  const filteredHistory = useMemo(() => {
    if (!ledger) return [];

    // If searching by account ID
    if (selectedAccountId) {
      return ledger.filter(
        (entry) =>
          entry.from_account_id === selectedAccountId ||
          entry.to_account_id === selectedAccountId
      );
    }

    // If searching by term
    if (searchTerm) {
      const term = searchTerm.toLowerCase();
      return ledger.filter(
        (entry) =>
          entry.event_type?.toLowerCase().includes(term) ||
          entry.from_account_id?.toLowerCase().includes(term) ||
          entry.to_account_id?.toLowerCase().includes(term)
      );
    }

    return ledger;
  }, [ledger, searchTerm, selectedAccountId]);

  // Sort by timestamp descending
  const sortedHistory = useMemo(() => {
    return [...filteredHistory].sort(
      (a, b) =>
        new Date(b.simulation_timestamp) - new Date(a.simulation_timestamp)
    );
  }, [filteredHistory]);

  return (
    <div className="history-view">
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <History size={18} />
              <span className="panel-title">Per-Person Transaction History</span>
              <span className="badge-count">
                {sortedHistory.length} Entries
              </span>
            </div>

            <div className="controls-bar">
              <div className="search-input-wrapper">
                <Search size={15} />
                <input
                  type="text"
                  placeholder="Search by account ID or event type..."
                  className="search-input"
                  value={searchTerm}
                  onChange={(e) => {
                    setSearchTerm(e.target.value);
                    setSelectedAccountId("");
                  }}
                />
              </div>

              <select
                className="select-filter"
                value={selectedAccountId}
                onChange={(e) => {
                  setSelectedAccountId(e.target.value);
                  setSearchTerm("");
                }}
              >
                <option value="">All Accounts (Search above)</option>
                {allAccountIds.slice(0, 50).map((id) => (
                  <option key={id} value={id}>
                    {id.slice(0, 12)}...
                  </option>
                ))}
                {allAccountIds.length > 50 && (
                  <option value="" disabled>
                    ({allAccountIds.length - 50} more accounts)
                  </option>
                )}
              </select>

              <button
                className="btn btn-outline"
                onClick={onRefresh}
                disabled={loading}
              >
                <RefreshCw size={12} className={loading ? "spinner" : ""} />
                <span>Refresh</span>
              </button>
            </div>
          </div>

          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Event Type</th>
                  <th>From</th>
                  <th>To</th>
                  <th>Amount</th>
                  <th>Direction</th>
                </tr>
              </thead>
              <tbody>
                {sortedHistory.length === 0 ? (
                  <tr>
                    <td colSpan="6">
                      <div className="empty-state">
                        <History size={32} />
                        <p>
                          {loading
                            ? "Loading history..."
                            : selectedAccountId || searchTerm
                              ? "No matching transactions found. Try a different search."
                              : "No history yet. Run the simulation first."}
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  sortedHistory.map((entry, i) => {
                    const typeClass = `tag-${
                      entry.event_type === "CREDIT" ||
                      entry.event_type === "SALARY_DEPOSIT"
                        ? "credit"
                        : entry.event_type === "DEBIT" ||
                          entry.event_type === "LIVING_COST" ||
                          entry.event_type === "PAYMENT_SETTLED"
                        ? "debit"
                        : entry.event_type === "SUBSCRIPTION"
                        ? "subscription"
                        : entry.event_type === "PAYMENT_FAILED"
                        ? "failed"
                        : "default"
                    }`;
                    const isCredit =
                      entry.event_type === "CREDIT" ||
                      entry.event_type === "SALARY_DEPOSIT";
                    const isDebit =
                      entry.event_type === "DEBIT" ||
                      entry.event_type === "LIVING_COST" ||
                      entry.event_type === "PAYMENT_SETTLED";
                    const isFailed = entry.event_type === "PAYMENT_FAILED";

                    return (
                      <tr key={entry.entry_id || i}>
                        <td className="mono-cell muted-cell">
                          {new Date(
                            entry.simulation_timestamp
                          ).toLocaleString()}
                        </td>
                        <td>
                          <span className={`tag-badge ${typeClass}`}>
                            {entry.event_type}
                          </span>
                        </td>
                        <td className="mono-cell">
                          {entry.from_account_id
                            ? entry.from_account_id.slice(0, 12) + "..."
                            : "—"}
                        </td>
                        <td className="mono-cell">
                          {entry.to_account_id
                            ? entry.to_account_id.slice(0, 12) + "..."
                            : "—"}
                        </td>
                        <td className="currency">
                          ₹
                          {parseFloat(entry.amount || 0).toLocaleString()}
                        </td>
                        <td>
                          {isCredit ? (
                            <span className="currency-positive">
                              ↗ Credit
                            </span>
                          ) : isDebit ? (
                            <span className="currency">↘ Debit</span>
                          ) : isFailed ? (
                            <span className="tag-failed-cell">Failed</span>
                          ) : (
                            <span className="currency">→ Transfer</span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {sortedHistory.length > 0 && (
            <div className="pagination">
              <div className="page-info">
                Displaying {sortedHistory.length} transactions
              </div>
            </div>
          )}
        </div>
      </ScrollFade>
    </div>
  );
};

export default PerPersonHistory;
