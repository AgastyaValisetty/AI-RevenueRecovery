import React, { useState, useEffect } from "react";
import {
  DollarSign,
  RefreshCw,
  BarChart3,
  Clock,
  Send,
  Store,
  Landmark,
  Percent,
} from "./ui/icons";
import ScrollFade from "./ui/ScrollFade";
import "./MerchantRevenueView.css";

const MerchantRevenueView = ({ merchants, loading, onRefresh }) => {
  const [revenueData, setRevenueData] = useState(null);
  const [selectedMerchant, setSelectedMerchant] = useState(null);
  const [processingPayments, setProcessingPayments] =
    useState(false);
  const [processResult, setProcessResult] = useState(null);
  const [expandedMerchant, setExpandedMerchant] = useState(null);

  const fetchRevenueData = async () => {
    try {
      const res = await fetch("/api/revenue");
      const data = await res.json();
      setRevenueData(data);
      if (data.merchants && data.merchants.length > 0 && !selectedMerchant) {
        setSelectedMerchant(data.merchants[0]);
      }
    } catch (e) {
      console.error("Failed to fetch revenue data:", e);
    }
  };

  useEffect(() => {
    fetchRevenueData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleProcessPayments = async () => {
    setProcessingPayments(true);
    setProcessResult(null);
    try {
      const res = await fetch("/api/payments/process-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      const data = await res.json();
      setProcessResult(data);
      await fetchRevenueData();
    } catch (e) {
      setProcessResult({ error: "Failed to process payments" });
    } finally {
      setProcessingPayments(false);
    }
  };

  const handleSelectMerchant = (merchant) => {
    setSelectedMerchant(merchant);
    setExpandedMerchant(merchant.merchant_id);
  };

  const formatCurrency = (amount) => {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(parseFloat(amount || 0));
  };

  const getRevenueClass = (amount) => {
    const val = parseFloat(amount || 0);
    if (val > 100000) return "high";
    if (val > 10000) return "medium";
    if (val > 0) return "low";
    return "zero";
  };

  if (loading || !revenueData) {
    return (
      <div className="revenue-view">
        <ScrollFade className="animate-scroll-fade">
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title-group">
                <DollarSign size={18} />
                <span className="panel-title">Merchant Revenue Analysis</span>
              </div>
            </div>
            <div className="panel-body">
              <div className="empty-state">
                <DollarSign size={32} />
                <p>Loading revenue data...</p>
              </div>
            </div>
          </div>
        </ScrollFade>
      </div>
    );
  }

  return (
    <div className="revenue-view">
      {/* Controls */}
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <DollarSign size={18} />
              <span className="panel-title">Revenue Controls</span>
              <span className="badge-count">
                {revenueData.total_lifetime_revenue
                  ? formatCurrency(revenueData.total_lifetime_revenue)
                  : "₹0"}
              </span>
            </div>
            <div className="controls-bar">
              <button
                className="btn btn-secondary"
                onClick={handleProcessPayments}
                disabled={processingPayments}
              >
                {processingPayments ? (
                  <>
                    <div className="spinner"></div>
                    <span>Processing...</span>
                  </>
                ) : (
                  <>
                    <Send size={12} />
                    <span>Process Pending Payments</span>
                  </>
                )}
              </button>
              <button
                className="btn btn-outline"
                onClick={() => {
                  fetchRevenueData();
                  onRefresh();
                }}
                disabled={loading}
              >
                <RefreshCw size={12} className={loading ? "spinner" : ""} />
                <span>Refresh</span>
              </button>
            </div>
          </div>

          <div className="panel-body">
            {processResult && (
              <div
                className={`process-result ${
                  processResult.error ? "error" : "success"
                }`}
              >
                {processResult.error ? (
                  processResult.error
                ) : (
                  `Processed ${processResult.processed} payments — ${processResult.settled} settled, ${processResult.failed} failed`
                )}
              </div>
            )}

            <div className="revenue-summary-bar">
              <div className="summary-stat">
                <span className="summary-label">Total Lifetime Revenue</span>
                <span className="summary-value">
                  {formatCurrency(revenueData.total_lifetime_revenue)}
                </span>
              </div>
              <div className="summary-stat summary-lazerpay">
                <span className="summary-label">
                  <Landmark size={13} /> LazerPay Revenue (2% cut)
                </span>
                <span className="summary-value">
                  {formatCurrency(revenueData.lazerpay_revenue)}
                </span>
              </div>
              <div className="summary-stat">
                <span className="summary-label">Active Merchants</span>
                <span className="summary-value">
                  {revenueData.merchant_count}
                </span>
              </div>
            </div>
          </div>
        </div>
      </ScrollFade>

      {/* Merchant Revenue Table */}
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <BarChart3 size={18} />
              <span className="panel-title">Revenue by Merchant</span>
            </div>
          </div>

          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Merchant</th>
                  <th>Type</th>
                  <th>Lifetime Revenue</th>
                  <th>LazerPay Cut (2%)</th>
                  <th>Transactions</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {revenueData.merchants.length === 0 ? (
                  <tr>
                    <td colSpan="6">
                      <div className="empty-state">
                        <p>
                          No merchants found. Run a simulation to generate
                          data.
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  revenueData.merchants.map((m) => (
                    <tr
                      key={m.merchant_id}
                      className={
                        expandedMerchant === m.merchant_id ? "expanded" : ""
                      }
                    >
                      <td className="primary-cell">{m.name}</td>
                      <td>
                        <span
                          className={`tag-badge ${
                            m.merchant_type === "SUBSCRIPTION_ONLY"
                              ? "tag-subscription"
                              : "tag-default"
                          }`}
                        >
                          {m.merchant_type}
                        </span>
                      </td>
                      <td className="currency">
                        {formatCurrency(m.lifetime_revenue)}
                      </td>
                      <td className="currency lazer-fee-cell">
                        <Percent size={12} />
                        {formatCurrency(m.lazerpay_fee)}
                      </td>
                      <td>
                        <span className="mono-cell">
                          {m.transaction_count}
                        </span>
                      </td>
                      <td>
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => handleSelectMerchant(m)}
                        >
                          View Details
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </ScrollFade>

      {/* Merchant Detail */}
      {selectedMerchant && (
        <ScrollFade className="animate-scroll-fade">
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title-group">
                <Store size={18} />
                <span className="panel-title">
                  {selectedMerchant.name}
                </span>
                <span className="badge-count">
                  {formatCurrency(selectedMerchant.lifetime_revenue)} revenue ·
                  LazerPay cut{" "}
                  {formatCurrency(selectedMerchant.lazerpay_fee)}
                </span>
              </div>
            </div>

            <div className="panel-body">
              {/* Monthly Revenue */}
              <div className="monthly-revenue-section">
                <h3 className="section-title">
                  <Clock size={14} />
                  Monthly Revenue Breakdown
                </h3>
                {selectedMerchant.monthly_revenue &&
                selectedMerchant.monthly_revenue.length > 0 ? (
                  <div className="monthly-grid">
                    {selectedMerchant.monthly_revenue
                      .slice()
                      .reverse()
                      .map((m) => (
                        <div key={m.month} className="monthly-card">
                          <div className="monthly-month">{m.month}</div>
                          <div className="monthly-amount">
                            {formatCurrency(m.total_revenue)}
                          </div>
                          <div className="monthly-count">
                            {m.transaction_count} txns
                          </div>
                        </div>
                      ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    <p>
                      No settled payments yet. Process pending payments to
                      generate revenue data.
                    </p>
                  </div>
                )}
              </div>

              {/* Individual Transactions */}
              <div className="transactions-section">
                <h3 className="section-title">
                  <DollarSign size={14} />
                  Individual Transactions (SETTLED)
                </h3>
                {selectedMerchant.recent_transactions &&
                selectedMerchant.recent_transactions.length > 0 ? (
                  <div className="table-responsive">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Transaction ID</th>
                          <th>Person ID</th>
                          <th>Amount</th>
                          <th>Payment Method</th>
                          <th>Status</th>
                          <th>Date</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedMerchant.recent_transactions.map((t) => (
                          <tr key={t.intent_id}>
                            <td className="mono-cell">
                              {t.intent_id.slice(0, 12)}...
                            </td>
                            <td className="mono-cell">
                              {t.person_id.slice(0, 12)}...
                            </td>
                            <td className="currency">
                              {formatCurrency(t.amount)}
                            </td>
                            <td className="mono-cell">{t.payment_method}</td>
                            <td>
                              <span className="tag-badge tag-credit">
                                {t.status}
                              </span>
                            </td>
                            <td className="mono-cell date-cell">
                              {t.created_at
                                ? new Date(t.created_at).toLocaleString()
                                : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="empty-state">
                    <p>No settled transactions for this merchant yet.</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </ScrollFade>
      )}
    </div>
  );
};

export default MerchantRevenueView;
