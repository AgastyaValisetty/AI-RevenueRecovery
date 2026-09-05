import React from "react";
import { Users, BookOpen, Storefront, PlayCircle, TrendingUp } from "./ui/icons";
import ScrollFade from "./ui/ScrollFade";

const Dashboard = ({
  people,
  merchants,
  simulation,
  bankStatus,
  loading,
  onRefresh,
  setActiveTab,
}) => {
  const summaryCards = [
    {
      title: "Total People",
      value: people?.length ?? 0,
      desc: "Active consumer profiles",
      icon: Users,
      onClick: () => setActiveTab && setActiveTab("people"),
    },
    {
      title: "Merchants",
      value: merchants?.length ?? 0,
      desc: "Ecosystem partners",
      icon: Storefront,
      onClick: () => setActiveTab && setActiveTab("merchants"),
    },
  ];

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
            <button
              className="btn btn-primary"
              style={{ marginTop: "14px" }}
              onClick={() => setActiveTab && setActiveTab("simulation")}
            >
              <PlayCircle size={16} />
              <span>Go to Simulation Runner</span>
            </button>
          </div>
          <div className="hero-mark">
            <TrendingUp size={40} />
            <span className="hero-mark-label">
              ₹{(Number(bankStatus?.volume_settled) || 0).toLocaleString("en-IN")}
            </span>
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
              <Users size={18} />
              <span className="panel-title">People</span>
              <span className="badge-count">{people?.length ?? 0} Profiles</span>
            </div>
            <button
              className="btn btn-outline"
              style={{ padding: "6px 12px", fontSize: "12px" }}
              onClick={() => setActiveTab && setActiveTab("people")}
            >
              View all
            </button>
          </div>
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Income Bracket</th>
                  <th>Spending Profile</th>
                  <th>Balance</th>
                </tr>
              </thead>
              <tbody>
                {(people ?? []).slice(0, 8).map((p, i) => (
                  <tr
                    key={p.person_id || i}
                    className="clickable-row"
                    onClick={() => setActiveTab && setActiveTab("people")}
                    style={{ cursor: "pointer" }}
                  >
                    <td className="primary-cell">{p.name || "—"}</td>
                    <td className="text-sm">{p.income_bracket || "—"}</td>
                    <td className="text-sm text-secondary">{p.spending_profile_category || "—"}</td>
                    <td className="mono-cell">₹{(Number(p.current_balance) || 0).toLocaleString("en-IN")}</td>
                  </tr>
                ))}
                {(!people || people.length === 0) && (
                  <tr>
                    <td colSpan="4">
                      <div className="empty-state">
                        <Users size={24} />
                        <p>Run the simulation to generate people.</p>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </ScrollFade>

      <ScrollFade className="animate-scroll-fade" style={{ animationDelay: "240ms" }}>
        <section className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Storefront size={18} />
              <span className="panel-title">Merchants</span>
              <span className="badge-count">{merchants?.length ?? 0} Partners</span>
            </div>
            <button
              className="btn btn-outline"
              style={{ padding: "6px 12px", fontSize: "12px" }}
              onClick={() => setActiveTab && setActiveTab("merchants")}
            >
              View all
            </button>
          </div>
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Merchant</th>
                  <th>Type</th>
                  <th>ID</th>
                </tr>
              </thead>
              <tbody>
                {(merchants ?? []).slice(0, 8).map((m, i) => (
                  <tr
                    key={m.merchant_id || i}
                    className="clickable-row"
                    onClick={() => setActiveTab && setActiveTab("merchants")}
                    style={{ cursor: "pointer" }}
                  >
                    <td className="primary-cell">{m.name || "—"}</td>
                    <td className="text-sm">{m.merchant_type || "—"}</td>
                    <td className="mono-cell text-xs text-tertiary">
                      {m.merchant_id ? m.merchant_id.slice(0, 8) + "…" : "—"}
                    </td>
                  </tr>
                ))}
                {(!merchants || merchants.length === 0) && (
                  <tr>
                    <td colSpan="3">
                      <div className="empty-state">
                        <Storefront size={24} />
                        <p>Run the simulation to generate merchants.</p>
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