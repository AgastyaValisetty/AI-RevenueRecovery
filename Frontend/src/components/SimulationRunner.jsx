import React, { useState } from 'react';
import { Play, RefreshCw, Clock, Activity, Users, Calendar, CheckCircle2 } from './ui/icons';
import { runParallelExperiment } from '../api';
import ScrollFade from './ui/ScrollFade';
import "./SimulationRunner.css";

export default function SimulationRunner({ simulation, onRefresh, onComparisonComplete }) {
  const [peopleCount, setPeopleCount] = useState(100);
  const [daysToRun, setDaysToRun] = useState(30);
  const [seed, setSeed] = useState(42);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [lastResult, setLastResult] = useState(null);

  const runSimulation = async (days) => {
    if (!days || days <= 0) {
      setMessage("Please enter a valid number of days");
      return;
    }

    setLoading(true);
    setMessage(`Running ${days}-day simulation for ${peopleCount} people (seed=${seed})...`);

    try {
      const data = await runParallelExperiment(peopleCount, days * 24, seed);
      setLastResult(data);
      onComparisonComplete?.(data);
      setMessage(`Completed! Baseline and SARA ran on ${peopleCount} people for ${days} days (seed=${seed}).`);
      onRefresh();
    } catch (e) {
      setMessage("Simulation failed. Check console for details.");
      console.error("Simulation error:", e);
    } finally {
      setLoading(false);
    }
  };

  const handleRunCustom = () => {
    runSimulation(daysToRun);
  };

  const presetDays = [1, 7, 31, 60, 90];

  return (
    <div className="sim-runner">
      <ScrollFade className="animate-scroll-fade">
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Users size={18} />
              <span className="panel-title">Population &amp; Time Horizon</span>
            </div>
          </div>

          <div className="sim-form-container">
            <form
              className="sim-form-grid"
              onSubmit={(e) => {
                e.preventDefault();
                handleRunCustom();
              }}
            >
              <div className="form-group">
                <label className="form-label">People Count</label>
                <input
                  type="number"
                  min="1"
                  max="10000"
                  step="1"
                  className="form-input"
                  value={peopleCount}
                  onChange={(e) => setPeopleCount(Math.max(1, parseInt(e.target.value) || 1))}
                  disabled={loading}
                />
                <span className="sim-hint">Number of people to seed (1-10000)</span>
              </div>

              <div className="form-group">
                <label className="form-label">Days to Advance</label>
                <input
                  type="number"
                  min="0"
                  max="365"
                  className="form-input"
                  value={daysToRun}
                  onChange={(e) => setDaysToRun(Math.max(1, parseInt(e.target.value) || 1))}
                  disabled={loading}
                />
                <span className="sim-hint">Advance the simulation clock (1-365 days)</span>
              </div>

              <div className="form-group">
                <label className="form-label">Seed (override)</label>
                <input
                  type="number"
                  className="form-input"
                  value={seed}
                  onChange={(e) => setSeed(parseInt(e.target.value) || 0)}
                  disabled={loading}
                />
                <span className="sim-hint">Random seed (default 42 — same seed = same population)</span>
              </div>

              <div>
                <button
                  type="submit"
                  className="btn btn-primary"
                  style={{ width: '100%' }}
                  disabled={loading}
                >
                  {loading ? (
                    <>
                      <div className="spinner"></div>
                      <span>Simulating…</span>
                    </>
                  ) : (
                    <>
                      <Play size={16} />
                      <span>Run {daysToRun} Days</span>
                    </>
                  )}
                </button>
              </div>
            </form>

            {message && (
              <div className={`sim-message ${loading ? "info" : "success"}`}>
                {message}
              </div>
            )}

            <div className="sim-presets">
              <span className="sim-preset-label">Quick presets:</span>
              {presetDays.map((d) => (
                <button
                  key={d}
                  className="sim-preset-btn"
                  onClick={() => runSimulation(d)}
                  disabled={loading}
                >
                  {d} day{d !== 1 ? "s" : ""}
                </button>
              ))}
            </div>

            {lastResult && lastResult.summary && (
              <div className="sim-result">
                <div className="sim-result-header">
                  <CheckCircle2 size={16} />
                  <span>Simulation Executed Successfully</span>
                </div>
                <div className="sim-result-grid">
                  {Object.entries(lastResult.summary).map(([key, val]) => (
                    <div key={key} className="sim-result-item">
                      <div className="sim-result-label">
                        {key.replace('_', ' ')}
                      </div>
                      <div className="sim-result-value">
                        {typeof val === 'number' ? val.toLocaleString() : String(val)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </ScrollFade>

      <ScrollFade className="animate-scroll-fade" style={{ animationDelay: "80ms" }}>
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Activity size={18} />
              <span className="panel-title">Current Simulation Status</span>
            </div>
          </div>
          <div className="sim-status-container">
            <div className="sim-status-grid">
              <div className="sim-status-item">
                <span className="sim-status-label">Current Day</span>
                <span className="sim-status-value">{simulation.currentDayDisplay || "—"}</span>
              </div>
              <div className="sim-status-item">
                <span className="sim-status-label">Current Date</span>
                <span className="sim-status-value">{simulation.currentDate || "—"}</span>
              </div>
              <div className="sim-status-item">
                <span className="sim-status-label">Status</span>
                <span className={`sim-status-value ${simulation.isRunning ? "running" : "paused"}`}>
                  {simulation.isRunning ? "Running" : "Paused"}
                </span>
              </div>
            </div>

            <button
              className="btn btn-secondary"
              onClick={onRefresh}
              disabled={loading}
            >
              <RefreshCw size={16} />
              <span>Refresh Status</span>
            </button>
          </div>
        </div>
      </ScrollFade>

      <ScrollFade className="animate-scroll-fade" style={{ animationDelay: "160ms" }}>
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <Clock size={18} />
              <span className="panel-title">Execution Lifecycle Phases</span>
            </div>
          </div>
          <div className="lifecycle-container">
            <div className="lifecycle-steps">
              <div className="lifecycle-step">
                <div className="lifecycle-step-num">1</div>
                <div>
                  <div className="lifecycle-step-title">Salary Credit Phase (09:00 UTC)</div>
                  <div className="lifecycle-step-desc">
                    Checks if current simulation day matches the person's salary deposit day. If matched, appends <code className="code-inline">SALARY_DEPOSIT</code> to the double-entry ledger.
                  </div>
                </div>
              </div>

              <div className="lifecycle-step">
                <div className="lifecycle-step-num">2</div>
                <div>
                  <div className="lifecycle-step-title">Subscription Due Check (10:00 UTC)</div>
                  <div className="lifecycle-step-desc">
                    Finds all active subscriptions due on the current date, generating <code className="code-inline">PaymentIntent</code> records with payment methods (UPI, Card, Netbanking).
                  </div>
                </div>
              </div>

              <div className="lifecycle-step">
                <div className="lifecycle-step-num">3</div>
                <div>
                  <div className="lifecycle-step-title">Living Cost Deduction Phase (12:00 UTC)</div>
                  <div className="lifecycle-step-desc">
                    Computes daily variable living expenses (1-3% of monthly salary based on spending profile) and logs <code className="code-inline">LIVING_COST</code> debits to the ledger.
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </ScrollFade>
    </div>
  );
}
