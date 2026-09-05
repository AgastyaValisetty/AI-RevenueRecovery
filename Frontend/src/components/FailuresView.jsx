import React, { useState, useMemo } from "react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { AlertOctagon, Search, TrendingUp, Inbox } from "./ui/icons";
import ScrollFade from "./ui/ScrollFade";
import "./FailuresView.css";

// Muted pastel palette for the pie chart — no AI-slop neon.
const PIE_COLORS = [
  "var(--pale-red)",
  "var(--pale-yellow)",
  "var(--pale-blue)",
  "var(--pale-green)",
];

// Category → display label + ordering, matching the user's taxonomy.
const CATEGORY_LABELS = [
  ["CUSTOMER_STATE", "Customer State"],
  ["BANK_DECLINE", "Bank Decline"],
  ["INFRASTRUCTURE", "Infrastructure"],
  ["MERCHANT_CONFIG", "Merchant / Config"],
  ["UNKNOWN", "Unknown"],
];
const categoryLabel = (cat) =>
  (CATEGORY_LABELS.find(([k]) => k === cat) || [null, cat])[1] || "Other";

// Tint a failure code by how hard/certain it is.
const reasonTone = (code) => {
  switch (code) {
    case "INSUFFICIENT_FUNDS":
    case "RISK_DECLINE":
    case "ISSUER_DECLINE":
      return "bar-rose";
    case "NETWORK_ERROR":
    case "TIMEOUT":
    case "BANK_DEGRADED":
    case "LIMIT_EXCEEDED":
    case "EXPIRED_PAYMENT_METHOD":
    case "AUTHENTICATION_FAILURE":
    case "INVALID_DETAILS":
      return "bar-amber";
    default:
      return "bar-neutral";
  }
};

const FailuresView = ({ failures, loading, onRefresh }) => {
  const [search, setSearch] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 50;

  const byReason = failures?.by_reason ?? [];
  const recent = failures?.recent_failures ?? [];
  const totalFailed = failures?.total_failed ?? 0;
  const totalSettled = failures?.total_settled ?? 0;
  const failureRate = failures?.failure_rate ?? 0;

  const filtered = useMemo(() => {
    if (!search.trim()) return recent;
    const q = search.toLowerCase();
    return recent.filter(
      (f) =>
        (f.failure_code && f.failure_code.toLowerCase().includes(q)) ||
        (f.failure_reason && f.failure_reason.toLowerCase().includes(q)) ||
        (f.merchant_id && f.merchant_id.toLowerCase().includes(q))
    );
  }, [recent, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const paginated = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filtered.slice(start, start + pageSize);
  }, [filtered, currentPage]);

  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= totalPages) setCurrentPage(newPage);
  };

  return (
    <div className="failures-view">
      {/* Summary cards */}
      <div className="failures-stats">
        <div className="stat-card stat-failed">
          <div className="stat-card-label">Failed Payments</div>
          <div className="stat-card-value">
            {totalFailed.toLocaleString()}
          </div>
        </div>
        <div className="stat-card stat-settled">
          <div className="stat-card-label">Settled Payments</div>
          <div className="stat-card-value">
            {totalSettled.toLocaleString()}
          </div>
        </div>
        <div className="stat-card stat-rate">
          <div className="stat-card-label">
            <TrendingUp size={14} /> Failure Rate
          </div>
          <div
            className={`stat-card-value ${failureRate > 10 ? "rate-high" : ""}`}
          >
            {failureRate.toFixed(2)}%
          </div>
          <div className="stat-card-sub">
            failed / (settled + failed)
          </div>
        </div>
      </div>

      {/* Reason breakdown */}
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <AlertOctagon size={18} />
              <span className="panel-title">
                Failure Breakdown by Reason
              </span>
              <span className="badge-count">
                {byReason.length} reasons
              </span>
            </div>
          </div>
          {byReason.length === 0 ? (
            <div className="empty-state">
              <Inbox size={32} />
              <p>
                {loading
                  ? "Loading failure breakdown..."
                  : "No recorded failures yet. Run the simulation to see failure reasons."}
              </p>
            </div>
          ) : (
            (() => {
              // Group reasons by category, preserving the taxonomy order.
              const grouped = CATEGORY_LABELS.map(([cat]) => ({
                category: cat,
                label: categoryLabel(cat),
                reasons: byReason.filter(
                  (r) => (r.category || "UNKNOWN") === cat
                ),
              })).filter((g) => g.reasons.length > 0);
              const ungrouped = byReason.filter(
                (r) =>
                  !CATEGORY_LABELS.some(
                    ([cat]) => cat === (r.category || "UNKNOWN")
                  )
              );
              if (ungrouped.length) {
                grouped.push({
                  category: "OTHER",
                  label: "Other",
                  reasons: ungrouped,
                });
              }
              return (
                <div className="breakdown-list">
                  {grouped.map((g) => (
                    <div className="breakdown-group" key={g.category}>
                      <div className="breakdown-group-header">
                        <span className="breakdown-group-label">
                          {g.label}
                        </span>
                        <span className="breakdown-group-count">
                          {g.reasons.reduce((s, r) => s + r.count, 0)} failures
                        </span>
                      </div>
                      {g.reasons.map((r) => (
                        <div
                          className="breakdown-row"
                          key={r.code}
                        >
                          <div className="breakdown-main">
                            <div className="breakdown-header">
                              <span className="reason-code">
                                {r.code}
                              </span>
                              <span className="reason-label">
                                {r.reason}
                              </span>
                            </div>
                            <div className="bar-track">
                              <div
                                className={`bar-fill ${reasonTone(r.code)}`}
                                style={{
                                  transform: `scaleX(${Math.max(
                                    0.02,
                                    (r.pct_of_failures || 0) / 100
                                  )})`,
                                }}
                              />
                            </div>
                          </div>
                          <div className="breakdown-meta">
                            <span className="breakdown-count">
                              {r.count}
                            </span>
                            <span className="breakdown-pct">
                              {r.pct_of_failures}%
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              );
            })()
          )}
        </div>
      </ScrollFade>

      {/* Failure-count pie chart */}
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <span className="panel-title">
                Failure Distribution
              </span>
              <span className="badge-count">by reason</span>
            </div>
          </div>
          {byReason.length === 0 ? (
            <div className="empty-state">
              <Inbox size={32} />
              <p>No failure data to chart yet.</p>
            </div>
          ) : (
            <div className="pie-wrap">
              <ResponsiveContainer width="100%" height={320}>
                <PieChart>
                  <Pie
                    data={byReason}
                    dataKey="count"
                    nameKey="code"
                    cx="50%"
                    cy="50%"
                    outerRadius={120}
                    innerRadius={55}
                    paddingAngle={2}
                    label={({ code, percent }) =>
                      percent >= 0.04
                        ? `${code} ${(percent * 100).toFixed(0)}%`
                        : ""
                    }
                  >
                    {byReason.map((entry, i) => (
                      <Cell
                        key={`cell-${entry.code}`}
                        fill={PIE_COLORS[i % PIE_COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value, name) => [
                      `${value.toLocaleString()}`,
                      name,
                    ]}
                    contentStyle={{
                      background: "var(--surface)",
                      border: "1px solid var(--border)",
                      borderRadius: "8px",
                      color: "var(--text-primary)",
                    }}
                  />
                  <Legend
                    wrapperStyle={{
                      fontFamily: "var(--font-mono)",
                      fontSize: "11px",
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </ScrollFade>

      {/* Recent failures table */}
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <span className="panel-title">
                Recent Failed Payments
              </span>
              <span className="badge-count">
                {recent.length} shown
              </span>
            </div>
            <div className="controls-bar">
              <div className="search-input-wrapper">
                <Search size={15} />
                <input
                  type="text"
                  placeholder="Search reason, code or merchant..."
                  className="search-input"
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setCurrentPage(1);
                  }}
                />
              </div>
              <button
                className="btn btn-outline"
                onClick={onRefresh}
                disabled={loading}
              >
                <span>Refresh</span>
              </button>
            </div>
          </div>

          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Reason</th>
                  <th>Person</th>
                  <th>Merchant</th>
                  <th>Amount</th>
                  <th>Method</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {paginated.length === 0 ? (
                  <tr>
                    <td colSpan="6">
                      <div className="empty-state">
                        <Inbox size={32} />
                        <p>
                          {loading
                            ? "Loading failures..."
                            : "No failed payments to show."}
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  paginated.map((f, i) => (
                    <tr
                      key={`${f.related_attempt_id || f.simulation_timestamp}-${i}`}
                    >
                      <td>
                        <span className="tag-badge tag-failed">
                          {f.failure_code}
                        </span>
                        <div className="reason-sub">
                          {f.failure_reason}
                        </div>
                      </td>
                      <td className="mono-cell">
                        {f.person_id
                          ? `${f.person_id.slice(0, 8)}…`
                          : "—"}
                      </td>
                      <td className="mono-cell">
                        {f.merchant_id
                          ? `${f.merchant_id.slice(0, 8)}…`
                          : "—"}
                      </td>
                      <td className="currency">
                        ₹{parseFloat(f.amount || 0).toLocaleString()}
                      </td>
                      <td className="mono-cell">{f.payment_method || "—"}</td>
                      <td className="mono-cell">
                        {f.simulation_timestamp
                          ? new Date(f.simulation_timestamp).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {filtered.length > 0 && (
            <div className="pagination">
              <div className="page-info">
                Showing {(currentPage - 1) * pageSize + 1} to{" "}
                {Math.min(currentPage * pageSize, filtered.length)} of{" "}
                {filtered.length} failures
              </div>
              <div className="page-actions">
                <button
                  className="btn btn-secondary"
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

export default FailuresView;
