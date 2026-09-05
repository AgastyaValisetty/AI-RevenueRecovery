import React from 'react';
import { Activity, Users, BookOpen, Repeat, Storefront, Database, PlayCircle, RefreshCw, Calendar, Layers } from './ui/icons';

export default function Navbar({ activeTab, setActiveTab, status, onRefresh, loading }) {
  const currentDate = status?.current_date || '2024-01-01';
  const currentDay = status?.current_day !== undefined ? status.current_day : 0;

  return (
    <header className="navbar">
      <div className="navbar-inner">
        <div className="brand">
          <div className="brand-icon">
            <Layers size={22} />
          </div>
          <div>
            <div className="brand-title">Revenue Recovery OS</div>
            <div className="brand-subtitle">Simulation Portal</div>
          </div>
        </div>

        <nav className="nav-tabs">
          <button
            className={`nav-tab ${activeTab === 'overview' ? 'active' : ''}`}
            onClick={() => setActiveTab('overview')}
          >
            <Activity size={15} />
            <span>Overview</span>
          </button>
          <button
            className={`nav-tab ${activeTab === 'people' ? 'active' : ''}`}
            onClick={() => setActiveTab('people')}
          >
            <Users size={15} />
            <span>People ({status?.people ?? 0})</span>
          </button>
          <button
            className={`nav-tab ${activeTab === 'ledger' ? 'active' : ''}`}
            onClick={() => setActiveTab('ledger')}
          >
            <BookOpen size={15} />
            <span>Ledger ({status?.ledger_entries ?? 0})</span>
          </button>
          <button
            className={`nav-tab ${activeTab === 'subscriptions' ? 'active' : ''}`}
            onClick={() => setActiveTab('subscriptions')}
          >
            <Repeat size={15} />
            <span>Subscriptions ({status?.subscriptions ?? 0})</span>
          </button>
          <button
            className={`nav-tab ${activeTab === 'merchants' ? 'active' : ''}`}
            onClick={() => setActiveTab('merchants')}
          >
            <Storefront size={15} />
            <span>Merchants</span>
          </button>
          <button
            className={`nav-tab ${activeTab === 'tables' ? 'active' : ''}`}
            onClick={() => setActiveTab('tables')}
          >
            <Database size={15} />
            <span>Tables Schema</span>
          </button>
          <button
            className={`nav-tab ${activeTab === 'simulation' ? 'active' : ''}`}
            onClick={() => setActiveTab('simulation')}
          >
            <PlayCircle size={15} />
            <span>Simulate</span>
          </button>
        </nav>

        <div className="nav-actions">
          <div className="status-badge" title="Simulation Clock Date">
            <Calendar size={13} />
            <span>Day {currentDay}: {currentDate}</span>
          </div>

          <button
            className="btn btn-outline"
            onClick={onRefresh}
            disabled={loading}
            title="Refresh Status"
          >
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>
    </header>
  );
}
