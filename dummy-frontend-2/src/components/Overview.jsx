import React from 'react';
import { Users, BookOpen, Repeat, CreditCard, Calendar, ArrowRight, Play } from './ui/icons';
import ScrollFade from './ui/ScrollFade';

export default function Overview({ status, setActiveTab, onQuickRun, loading }) {
  const currentDate = status?.current_date || '2024-01-01';
  const currentDay = status?.current_day !== undefined ? status.current_day : 0;

  const cards = [
    {
      title: 'Current Clock Date',
      value: currentDate,
      desc: `Simulation Day ${currentDay} of 90 (Q1 2024)`,
      icon: Calendar,
      tab: 'simulation',
      isDate: true,
    },
    {
      title: 'People Simulated',
      value: status?.people ?? 0,
      desc: 'Active synthetic consumer profiles',
      icon: Users,
      tab: 'people',
    },
    {
      title: 'Ledger Entries',
      value: status?.ledger_entries ?? 0,
      desc: 'Immutable double-entry transaction log',
      icon: BookOpen,
      tab: 'ledger',
    },
    {
      title: 'Active Subscriptions',
      value: status?.subscriptions ?? 0,
      desc: 'Recurring monthly billing profiles',
      icon: Repeat,
      tab: 'subscriptions',
    },
    {
      title: 'Payment Intents',
      value: status?.payment_intents ?? 0,
      desc: 'Queued transactions for billing runs',
      icon: CreditCard,
      tab: 'tables',
    },
  ];

  const quickRunButtons = [
    { label: 'Advance +1 Day', days: 1, variant: 'primary' },
    { label: 'Advance +7 Days', days: 7, variant: 'secondary' },
    { label: 'Advance +31 Days', days: 31, variant: 'secondary' },
    { label: 'Advance +60 Days', days: 60, variant: 'secondary' },
  ];

  return (
    <div>
      <ScrollFade className="animate-scroll-fade">
        <div className="stats-grid">
          {cards.map((card, idx) => {
            const Icon = card.icon;
            return (
              <div
                key={idx}
                className="stat-card"
                style={{ '--index': idx }}
                onClick={() => card.tab && setActiveTab(card.tab)}
              >
                <div className="stat-card-header">
                  <span className="stat-title">{card.title}</span>
                  <div className="stat-icon-wrapper">
                    <Icon size={18} />
                  </div>
                </div>
                <div className="stat-value">
                  {card.isDate ? card.value : card.value.toLocaleString()}
                </div>
                <div className="stat-desc">{card.desc}</div>
              </div>
            );
          })}
        </div>
      </ScrollFade>

      <ScrollFade className="animate-scroll-fade">
        <div className="panel" style={{ '--index': 1 }}>
          <div className="panel-header">
            <div className="panel-title-group">
              <BookOpen size={18} />
              <span className="panel-title">Multi-Month Simulation Advancer</span>
              <span className="badge-count">Current: {currentDate}</span>
            </div>
            <button
              className="btn btn-outline"
              onClick={() => setActiveTab('simulation')}
            >
              <span>Advanced Controls</span>
              <ArrowRight size={14} />
            </button>
          </div>
          <div className="overview-body">
            <p className="overview-desc">
              Advance the clock across January, February, March, and beyond. Every day applies monthly salary credits on people's deposit days, calculates dynamic daily living costs, and rolls subscriptions forward to their next billing cycle (30 days ahead).
            </p>

            <div className="quick-run-grid">
              {quickRunButtons.map((btn, i) => (
                <button
                  key={i}
                  className={`btn ${btn.variant === 'primary' ? 'btn-primary' : 'btn-secondary'}`}
                  onClick={() => onQuickRun(100, btn.days)}
                  disabled={loading}
                >
                  <Play size={14} />
                  <span>{btn.label}</span>
                </button>
              ))}
              <button
                className="btn btn-outline"
                onClick={() => setActiveTab('ledger')}
              >
                <BookOpen size={14} />
                <span>View Recent 250 Ledger Records</span>
              </button>
            </div>
          </div>
        </div>
      </ScrollFade>
    </div>
  );
}
