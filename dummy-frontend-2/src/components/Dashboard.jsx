import React from "react";
import { Users, BookOpen, Repeat, CreditCard, TrendingUp } from "./ui/icons";
import { money, pct, formatCurrency } from "../utils/format";
import ScrollFade from "./ui/ScrollFade";

const Dashboard = ({ people, ledger, simulation, bankStatus, loading, onRefresh, setActiveTab }) => {
  const summaryCards = [
    {
      title: "Total People",
      value: people?.length ?? 0,
      desc: "Active consumer profiles",
      icon: Users,
      onClick: () => setActiveTab && setActiveTab("people"),
    },
    {
      title: "Ledger Entries",
      value: ledger?.length ?? 0,
      desc: "Recorded transactions",
      icon: BookOpen,
      onClick: () => setActiveTab && setActiveTab("transactions"),
    },
    {
      title: "Active Subscriptions",
      value: simulation?.subscriptions ?? 0,
      desc: "Recurring billing",
      icon: Repeat,
      onClick: () => setActiveTab && setActiveTab("merchants"),
    },
    {
      title: "Bank Status",
      value: bankStatus?.current_state || "—",
      desc: `${pct(bankStatus?.authorization_success_rate, 100) || "—"} auth success`,
      icon: CreditCard,
    },
  ];

  const failureRate = Number(bankStatus?.failure_rate || 0);
  const successRate = Number(bankStatus?.success_rate || 0);

  return (
    <div className="dashboard">
      <ScrollFade className="animate-scroll-fade">
        <section className="dashboard-hero">
          <div>
            <div className="eyebrow">
              <span className="eyebrow-dot" />
              <span>Simulation clock {simulation?.isRunning ? "running" : "paused"}</span>
            </div>
            <h2 className="hero-title">Payment recovery dashboard</h2>
            <p className="hero-subtitle">
              Day {simulation?.currentDayDisplay ?? "—"} • {simulation?.currentDate ?? "—"}
            </p>
          </div>
          <div className="hero-mark">
            <TrendingUp size={40} />
            <span className="hero-mark-label">₹{(Number(bankStatus?.volume_settled) || 0).toLocaleString('en-IN')}</span>
          </div>
        </section>
      </ScrollFade>

      <ScrollFade className="animate-scroll-fade" style={{ animationDelay: "80ms" }}>
        <div className="stats-grid">
          {summaryCards.map((card, idx) => {
            const Icon = card.icon;
            return (
              <div
                key={idx}
                className="stat-card"
                style={{ "--index": idx, cursor: card.onClick ? "pointer" : "default" }}
                onClick={card.onClick}
              >
                <div className="stat-card-header">
                  <span className="stat-title">{card.title}</span>
                  <div className="stat-icon-wrapper">
                    <Icon size={18} />
                  </div>
                </div>
                <div className="stat-value">{Number(card.value).toLocaleString()}</div>
                <div className="stat-desc">{card.desc}</div>
              </div>
            );
          })}
        </div>
      </ScrollFade>

      <ScrollFade className="animate-scroll-fade" style={{ animationDelay: "160ms" }}>
        <section className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <CreditCard size={18} />
              <span className="panel-title">Bank Health</span>
            </div>
            <button
              className="btn btn-outline"
              style={{ padding: "6px 12px", fontSize: "12px" }}
              onClick={onRefresh}
              disabled={loading}
            >
              Refresh
            </button>
          </div>
          <div className="bank-health-grid">
            <div className="health-item">
              <span className="health-label">Success rate</span>
              <span className="health-value">{pct(successRate, 100)}</span>
            </div>
            <div className="health-item">
              <span className="health-label">Failure rate</span>
              <span className="health-value">{pct(failureRate, 100)}</span>
            </div>
            <div className="health-item">
              <span className="health-label">Volume settled</span>
              <span className="health-value">{formatCurrency(Number(bankStatus?.volume_settled) || 0)}</span>
            </div>
            <div className="health-item">
              <span className="health-label">Current state</span>
              <span className={`tag-badge ${bankStatus?.current_state ? `state-${bankStatus.current_state.toLowerCase()}` : "tag-default"}`}>
                {bankStatus?.current_state || "—"}
              </span>
            </div>
          </div>
        </section>
      </ScrollFade>

      <ScrollFade className="animate-scroll-fade" style={{ animationDelay: "240ms" }}>
        <section className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <BookOpen size={18} />
              <span className="panel-title">Recent Ledger Activity</span>
            </div>
          </div>
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Amount</th>
                  <th>Time</th>
                </tr>
              </thead>
              <tbody>
                {(ledger ?? []).slice(0, 8).map((entry, i) => (
                  <tr key={i}>
                    <td className="primary-cell" style={{ fontSize: "12px" }}>{entry.event_type}</td>
                    <td className="mono-cell">
                      <span className={entry.event_type?.includes("DEPOSIT") ? "currency-positive" : "currency"}>
                        {entry.event_type?.includes("DEPOSIT") ? "+" : "-"}₹{(Number(entry.amount) || 0).toLocaleString('en-IN', { minimumFractionDigits: 0 })}
                      </span>
                    </td>
                    <td className="mono-cell" style={{ fontSize: "11px" }}>
                      {entry.timestamp || entry.simulation_timestamp || "—"}
                    </td>
                  </tr>
                ))}
                {(!ledger || ledger.length === 0) && (
                  <tr>
                    <td colSpan="3">
                      <div className="empty-state">
                        <BookOpen size={24} />
                        <p>Run the simulation to generate ledger activity.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </ScrollFade>
    </div>
  );
};

export default Dashboard;
