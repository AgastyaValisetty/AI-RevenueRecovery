import React from "react";
import {
  LayoutDashboard,
  PlayCircle,
  Users,
  BookOpen,
  Store,
  CreditCard,
  History,
  DollarSign,
  AlertOctagon,
  RefreshCw,
  Trash2,
  GitBranch,
  Activity,
  ChevronLeft,
  ChevronRight,
} from "./ui/icons";
import "./Sidebar.css";

const mainTabs = [
  { key: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { key: "simulation", label: "Simulation", icon: PlayCircle },
  { key: "people", label: "People", icon: Users },
  { key: "transactions", label: "Ledger", icon: BookOpen },
  { key: "bank", label: "Bank", icon: CreditCard },
  { key: "history", label: "History", icon: History },
  { key: "merchants", label: "Merchants", icon: Store },
  { key: "revenue", label: "Revenue", icon: DollarSign },
  { key: "failures", label: "Failed Payments", icon: AlertOctagon },
  { key: "comparison", label: "Baseline vs SARA", icon: GitBranch },
];

const recoveryTabs = [
  { key: "recovery", label: "Recovery Agent", icon: RefreshCw },
  { key: "sara-attempts", label: "SARA Attempts", icon: Activity },
];

const Sidebar = ({ activeTab, setActiveTab, currentDay, currentDate, isRunning, collapsed, onToggle }) => {
  const renderNavSection = (sectionLabel, tabs) => (
    <>
      {!collapsed && sectionLabel && (
        <div className="sidebar-section-label">{sectionLabel}</div>
      )}
      <ul>
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <li key={tab.key}>
              <button
                className={`nav-item ${isActive ? "active" : ""}`}
                onClick={() => setActiveTab(tab.key)}
                style={{ "--index": 0 }}
              >
                <Icon size={18} className="nav-icon" />
                <span className="nav-label">{tab.label}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <div className="sidebar-header">
        <div className="sidebar-brand">
          <div className="brand-icon">
            <Activity size={24} />
          </div>
          <div>
            <h1 className="brand-title">Revenue Recovery</h1>
            <p className="brand-subtitle">Simulation Portal</p>
          </div>
        </div>
      </div>

      <div className="sidebar-status">
        <div className="status-chip">
          <span className={`status-dot ${isRunning ? "running" : "paused"}`}></span>
          <span>{isRunning ? "Running" : "Paused"}</span>
        </div>
        <div className="status-chip">
          <span className="text-muted">Day:</span>
          <span className="text-primary font-mono">{currentDay}</span>
        </div>
        <div className="status-chip">
          <span className="text-muted">Date:</span>
          <span className="text-primary font-mono">{currentDate}</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {renderNavSection("Overview", mainTabs)}
        {!collapsed && <div className="sidebar-divider" />}
        {renderNavSection("Recovery Agent", recoveryTabs)}
      </nav>

      <div className="sidebar-footer">
        <button
          className="sidebar-toggle"
          onClick={onToggle}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
        <button
          className="sidebar-nuke"
          title="Reset all data"
          onClick={async (e) => {
            e.preventDefault();
            if (!window.confirm("Reset all data — This will delete ALL tables and data. Cannot be undone. Are you sure?")) return;
            try {
              const res = await fetch("/api/simulation/nuke", { method: "POST" });
              const data = await res.json();
              if (res.ok) {
                window.location.reload();
              } else {
                alert("Reset failed: " + (data?.message || "Unknown error"));
              }
            } catch(err) {
              alert("Reset failed: " + err.message);
            }
          }}
        >
          <Trash2 size={16} />
          {!collapsed && <span>Reset DB</span>}
        </button>
      </div>
    </aside>
  );
};

export default Sidebar;
