import React, { useEffect, useState } from 'react';
import { GitBranch, Play, RefreshCw, ShieldCheck, TrendingUp, Users } from './ui/icons';
import { fetchParallelExperimentAudit, listParallelExperiments, runParallelExperiment } from '../api';
import ScrollFade from './ui/ScrollFade';
import { money, pct } from '../utils/format';
import './ComparisonView.css';

function Metric({ label, baseline, smart, format = (v) => v ?? '—' }) {
  return (
    <div className="comparison-metric">
      <span>{label}</span>
      <strong>{format(smart)}</strong>
      <small>Baseline {format(baseline)}</small>
    </div>
  );
}

export default function ComparisonView({ initialReport = null, onReport }) {
  const [report, setReport] = useState(initialReport);
  const [history, setHistory] = useState([]);
  const [form, setForm] = useState({ people: 100, days: 30, seed: 42 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [audit, setAudit] = useState({ engine: 'smart', events: [], loading: false });

  const loadHistory = async () => {
    try { setHistory((await listParallelExperiments(10)).experiments || []); } catch { /* optional */ }
  };
  useEffect(() => { loadHistory(); }, []);

  useEffect(() => {
    if (!report?.experiment_id || !report.schemas_preserved) return;
    setAudit(a => ({ ...a, loading: true }));
    fetchParallelExperimentAudit(report.experiment_id, audit.engine)
      .then(data => setAudit({ engine: audit.engine, events: data.events || [], loading: false }))
      .catch(() => setAudit(a => ({ ...a, events: [], loading: false })));
  }, [report?.experiment_id, report?.schemas_preserved, audit.engine]);

  const run = async (event) => {
    event.preventDefault();
    setLoading(true); setError('');
    try {
      const next = await runParallelExperiment(form.people, form.days * 24, form.seed);
      setReport(next); onReport?.(next); await loadHistory();
    } catch (err) { setError(err.message || 'The paired experiment could not be completed.'); }
    finally { setLoading(false); }
  };

  const baseline = report?.baseline || {};
  const smart = report?.smart || {};

  // Two rates for the comparison:
  //   - "Recovery percentage" (intent-level): recovered_cases / total_cases.
  //     What fraction of failed intents the engine actually recovered.
  //   - "Success rate" (retry-level): retries_successful / total_retries.
  //     What fraction of retry attempts succeeded.
  // Both shown side-by-side per user request.
  const baselineFailedPaymentRate = pct(baseline.recovered_cases, baseline.total_cases);
  const smartFailedPaymentRate = pct(smart.recovered_cases, smart.total_cases);

  const baselineRetryRate = pct(baseline.retries_successful, baseline.total_retries);
  const smartRetryRate = pct(smart.retries_successful, smart.total_retries);
  const retryRateDelta = (() => {
    const b = Number(baseline.retry_success_rate ?? 0);
    const s = Number(smart.retry_success_rate ?? 0);
    return `${(s - b >= 0 ? '+' : '')}${((s - b) * 100).toFixed(2)} pp`;
  })();

  const lift = Number(report?.incremental_recovered_value || 0);

  return (
    <div className="comparison-view">
      <ScrollFade className="animate-scroll-fade">
        <section className="comparison-hero">
          <div>
            <div className="eyebrow"><GitBranch size={14} /> Paired evaluation</div>
            <h2>Does SARA recover more money?</h2>
            <p>One deterministic population, two isolated runs, one honest scoreboard.</p>
          </div>
          <div className="comparison-hero-mark">SARA<br /><span>vs</span><br />BASE</div>
        </section>
      </ScrollFade>

      <ScrollFade className="animate-scroll-fade" style={{ '--index': 1 }}>
        <section className="panel comparison-config">
          <div className="panel-header">
            <div className="panel-title-group">
              <Play size={18} />
              <span className="panel-title">Run a paired simulation</span>
            </div>
          </div>
          <form onSubmit={run} className="comparison-form">
            <label>People<input type="number" min="1" max="10000" value={form.people} onChange={e => setForm({ ...form, people: Number(e.target.value) })} /></label>
            <label>Days<input type="number" min="1" max="365" value={form.days} onChange={e => setForm({ ...form, days: Number(e.target.value) })} /></label>
            <label>Seed<input type="number" min="0" value={form.seed} onChange={e => setForm({ ...form, seed: Number(e.target.value) })} /></label>
            <button className="btn btn-primary" disabled={loading}>
              <Play size={15} /> {loading ? 'Running both agents…' : 'Run comparison'}
            </button>
          </form>
          {error && <div className="comparison-error">{error}</div>}
        </section>
      </ScrollFade>

      {report ? (
        <>
          <ScrollFade className="animate-scroll-fade" style={{ '--index': 2 }}>
            <div className="comparison-run-meta">
              <span>Experiment <b>{report.experiment_id || 'latest'}</b></span>
              <span>Seed <b>{report.seed || form.seed}</b></span>
              <span><ShieldCheck size={14} /> isolated runs complete</span>
            </div>
          </ScrollFade>

          <ScrollFade className="animate-scroll-fade" style={{ '--index': 3 }}>
            <div className="comparison-scoreboard">
              <div className="score-card baseline">
                <span className="score-kicker">Baseline agent</span>
                <strong>{money(baseline.net_recovered_value)}</strong>
                <small>net recovered</small>
                <dl className="score-rate-row">
                  <div>
                    <dt>Recovery %</dt>
                    <dd>{baselineFailedPaymentRate}</dd>
                  </div>
                  <div>
                    <dt>Success rate</dt>
                    <dd>{baselineRetryRate}</dd>
                  </div>
                </dl>
              </div>
              <div className="score-card winner">
                <span className="score-kicker">SARA</span>
                <strong>{money(smart.net_recovered_value)}</strong>
                <small>net recovered</small>
                <em><TrendingUp size={14} /> {lift >= 0 ? '+' : ''}{money(lift)} vs baseline</em>
                <dl className="score-rate-row">
                  <div>
                    <dt>Recovery %</dt>
                    <dd>{smartFailedPaymentRate}</dd>
                  </div>
                  <div>
                    <dt>Success rate</dt>
                    <dd>{smartRetryRate}</dd>
                  </div>
                </dl>
              </div>
            </div>
          </ScrollFade>

          <ScrollFade className="animate-scroll-fade" style={{ '--index': 4 }}>
            <section className="panel">
              <div className="panel-header">
                <div className="panel-title-group">
                  <Users size={18} />
                  <span className="panel-title">Outcome breakdown</span>
                </div>
              </div>
              <div className="table-responsive">
                <table className="comparison-table">
                  <thead>
                    <tr><th>Metric</th><th>Baseline</th><th>SARA</th><th>Difference</th></tr>
                  </thead>
                  <tbody>
                    <tr><td>Recovery %<br /><small>(recovered / total failed intents)</small></td><td>{baselineFailedPaymentRate}</td><td>{smartFailedPaymentRate}</td><td>{Number(report.incremental_recovery_rate || 0).toFixed(2)} pp</td></tr>
                    <tr><td>Success rate<br /><small>(successful attempts / total attempts)</small></td><td>{baselineRetryRate}<br /><small className="text-muted">{baseline.retries_successful ?? 0} / {baseline.total_retries ?? 0}</small></td><td>{smartRetryRate}<br /><small className="text-muted">{smart.retries_successful ?? 0} / {smart.total_retries ?? 0}</small></td><td>{retryRateDelta}</td></tr>
                    <tr><td>Recovered value</td><td>{money(baseline.total_recovered_value)}</td><td>{money(smart.total_recovered_value)}</td><td>{money(Number(smart.total_recovered_value || 0) - Number(baseline.total_recovered_value || 0))}</td></tr>
                    <tr><td>Retries</td><td>{baseline.total_retries ?? 0}</td><td>{smart.total_retries ?? 0}</td><td>{(Number(smart.total_retries || 0) - Number(baseline.total_retries || 0))}</td></tr>
                    <tr><td>Wasted retries</td><td>{baseline.wasted_retries ?? 0}</td><td>{smart.wasted_retries ?? 0}</td><td>{Number(report.wasted_retry_reduction || 0)} saved</td></tr>
                    <tr><td>Safety incidents</td><td>{baseline.duplicate_risk_incidents ?? 0}</td><td>{smart.duplicate_risk_incidents ?? 0}</td><td>zero is best</td></tr>
                  </tbody>
                </table>
              </div>
              <div className="comparison-note">{report.notes || 'Both agents ran against the same requested seed and population.'}</div>
            </section>
          </ScrollFade>

          <ScrollFade className="animate-scroll-fade" style={{ '--index': 5 }}>
            <section className="panel comparison-audit">
              <div className="panel-header">
                <div className="panel-title-group">
                  <ShieldCheck size={17} />
                  <span className="panel-title">Decision audit trail</span>
                </div>
                <div className="audit-tabs">
                  <button className={audit.engine === 'baseline' ? 'active' : ''} onClick={() => setAudit(a => ({ ...a, engine: 'baseline' }))}>Baseline</button>
                  <button className={audit.engine === 'smart' ? 'active' : ''} onClick={() => setAudit(a => ({ ...a, engine: 'smart' }))}>SARA</button>
                </div>
              </div>
              {report.schemas_preserved ? (
                <div className="comparison-audit-list">
                  {audit.loading ? (
                    <span>Loading audit events…</span>
                  ) : audit.events.length ? (
                    audit.events.slice(0, 80).map(evt => (
                      <div key={evt.event_id}>
                        <time>{new Date(evt.timestamp).toLocaleString()}</time>
                        <b>{evt.decision_json?.action_type || evt.outcome || evt.event_type}</b>
                        <span>{evt.decision_json?.reason || 'Decision recorded'}</span>
                        <code>{(evt.input_snapshot_hash || '').slice(0, 10)}</code>
                      </div>
                    ))
                  ) : (
                    <span>No audit events recorded.</span>
                  )}
                </div>
              ) : (
                <div className="comparison-note">
                  Run with <code>?keep_schemas=true</code> to inspect per-agent audit events.
                </div>
              )}
            </section>
          </ScrollFade>
        </>
      ) : (
        <ScrollFade className="animate-scroll-fade" style={{ '--index': 2 }}>
          <div className="comparison-empty">
            <GitBranch size={26} />
            <p>Run the simulation to see baseline and SARA side by side.</p>
          </div>
        </ScrollFade>
      )}

      <ScrollFade className="animate-scroll-fade" style={{ '--index': 6 }}>
        <section className="panel comparison-history">
          <div className="panel-header">
            <div className="panel-title-group">
              <RefreshCw size={17} />
              <span className="panel-title">Recent comparisons</span>
            </div>
          </div>
          <div className="comparison-history-list">
            {history.length ? (
              history.map(item => (
                <div key={item.experiment_id}>
                  <code>{item.experiment_id}</code>
                  <span>{item.baseline_cases} baseline cases</span>
                  <strong>{money(item.lift)}</strong>
                </div>
              ))
            ) : (
              <span>No saved comparisons yet.</span>
            )}
          </div>
        </section>
      </ScrollFade>
    </div>
  );
}
