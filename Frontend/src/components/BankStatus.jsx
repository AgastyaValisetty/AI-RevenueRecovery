import React from "react";
import { CreditCard, RefreshCw, Activity, TrendingUp, TrendingDown } from "./ui/icons";
import { money, pct } from "../utils/format";
import ScrollFade from "./ui/ScrollFade";
import "./BankStatus.css";

const getStateColor = (state) => {
  switch (state) {
    case "NORMAL": return "state-normal";
    case "PEAK": return "state-peak";
    case "DEGRADED": return "state-degraded";
    case "OUTAGE": return "state-outage";
    default: return "";
  }
};

const BankStatus = ({ bankStatus, loading, onRefresh }) => {
  const state = bankStatus?.current_state || "NORMAL";

  return (
    <div className="bank-status-view">
      <ScrollFade className="animate-scroll-fade">
        <section className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <CreditCard size={18} />
              <span className="panel-title">Bank Status</span>
              <span className="badge-count">{bankStatus?.bank_name || "RupeeBank"}</span>
            </div>
            <button
              className="btn btn-outline"
              style={{ padding: "6px 12px", fontSize: "12px" }}
              onClick={onRefresh}
              disabled={loading}
            >
              <RefreshCw size={13} />
              Refresh
            </button>
          </div>

          <div className="bank-status-grid">
            <div className={`bank-state-badge ${getStateColor(state)}`}>
              <Activity size={16} />
              <span>{state}</span>
            </div>

            <div className="bank-metrics-grid">
              <div className="bank-metric">
                <span className="bank-metric-label">Authorization Success</span>
                <span className="bank-metric-value">{pct(bankStatus?.authorization_success_rate || 99.1, 100)}</span>
              </div>
              <div className="bank-metric">
                <span className="bank-metric-label">Timeout Rate</span>
                <span className="bank-metric-value">{pct(bankStatus?.timeout_rate || 0.3, 100)}</span>
              </div>
              <div className="bank-metric">
                <span className="bank-metric-label">Issuer Decline</span>
                <span className="bank-metric-value">{pct(bankStatus?.issuer_decline_rate || 0.4, 100)}</span>
              </div>
              <div className="bank-metric">
                <span className="bank-metric-label">Network Errors</span>
                <span className="bank-metric-value">{pct(bankStatus?.network_error_rate || 0.2, 100)}</span>
              </div>
            </div>

            <div className="bank-volume-row">
              <div className="bank-volume-item">
                <TrendingUp size={16} />
                <span className="bank-volume-label">Volume Settled</span>
                <span className="bank-volume-value">{money(bankStatus?.volume_settled)}</span>
              </div>
              <div className="bank-volume-item">
                <TrendingDown size={16} />
                <span className="bank-volume-label">Volume Failed</span>
                <span className="bank-volume-value">{money(bankStatus?.volume_failed)}</span>
              </div>
            </div>
          </div>
        </section>
      </ScrollFade>

      <ScrollFade className="animate-scroll-fade" style={{ animationDelay: "80ms" }}>
        <section className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Activity size={18} />
              <span className="panel-title">State Timeline</span>
            </div>
          </div>
          <div className="bank-timeline">
            {["NORMAL", "PEAK", "NORMAL", "DEGRADED", "NORMAL"].map((s, i) => (
              <div key={i} className="timeline-item">
                <div className={`timeline-dot ${getStateColor(s)}`}>
                  <span className="timeline-state">{s}</span>
                </div>
                <div className="timeline-content">
                  <div className="timeline-time">Day {i + 1}</div>
                  <div className="timeline-desc">Bank operated in {s.toLowerCase()} state</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      </ScrollFade>
    </div>
  );
};

export default BankStatus;
