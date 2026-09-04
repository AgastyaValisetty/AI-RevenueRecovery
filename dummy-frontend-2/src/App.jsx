import React, { useState, useEffect, useCallback } from "react";
import "./App.css";
import Sidebar from "./components/Sidebar";
import Dashboard from "./components/Dashboard";
import SimulationRunner from "./components/SimulationRunner";
import PeopleView from "./components/PeopleView";
import TransactionsView from "./components/TransactionsView";
import BankStatus from "./components/BankStatus";
import PerPersonHistory from "./components/PerPersonHistory";
import MerchantsTable from "./components/MerchantsTable";
import MerchantRevenueView from "./components/MerchantRevenueView";
import FailuresView from "./components/FailuresView";
import RecoveryView from "./components/RecoveryView";
import ComparisonView from "./components/ComparisonView";
import SaraAttemptsView from "./components/SaraAttemptsView";

// Map of tab keys to their display names
const TAB_TITLES = {
  dashboard: "Dashboard",
  simulation: "Simulation Runner",
  people: "People Directory",
  transactions: "Ledger Transactions",
  bank: "Bank Status",
  history: "Per-Person History",
  merchants: "Ecosystem Merchants",
  revenue: "Revenue Analysis",
  failures: "Failed Payments",
  recovery: "Recovery Agent",
  "recovery-metrics": "Recovery Metrics & Statistics",
  "recovery-audit": "Recovery Audit Trail",
  comparison: "Baseline vs SARA",
  "sara-attempts": "SARA Attempts Ledger",
};

function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [simulation, setSimulation] = useState({
    currentDay: null,
    currentDayDisplay: "—",
    currentDate: "—",
    isRunning: false,
  });
  const [people, setPeople] = useState([]);
  const [ledger, setLedger] = useState([]);
  const [bankStatus, setBankStatus] = useState({});
  const [merchants, setMerchants] = useState([]);
  const [failures, setFailures] = useState(null);
  const [recoveryMetrics, setRecoveryMetrics] = useState(null);
  const [recoveryActions, setRecoveryActions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [comparisonReport, setComparisonReport] = useState(null);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  // Fetch simulation status + refresh relevant data
  const fetchSimulationData = useCallback(async () => {
    try {
      const res = await fetch("/api/simulation/status");
      const data = await res.json();
      const day = data.current_day !== undefined ? `#${data.current_day}` : "—";
      setSimulation({
        currentDay: data.current_day,
        currentDayDisplay: day,
        currentDate: data.current_date || "—",
        isRunning: data.is_running || false,
      });
    } catch (e) {
      console.error("Failed to fetch simulation status:", e);
    }
  }, []);

  // Poll simulation status every 3 seconds
  useEffect(() => {
    fetchSimulationData();
    const id = setInterval(fetchSimulationData, 3000);
    return () => clearInterval(id);
  }, [fetchSimulationData]);

  // Fetch data for active tab
  const fetchDataForTab = useCallback(async (tab) => {
    setLoading(true);
    try {
      switch (tab) {
        case "people": {
          const res = await fetch("/api/people");
          const data = await res.json();
          setPeople(data.people ?? []);
          break;
        }

        case "transactions": {
          const res = await fetch("/api/ledger?limit=5000");
          const data = await res.json();
          setLedger(data.entries ?? []);
          break;
        }

        case "bank": {
          const res = await fetch("/api/status");
          const data = await res.json();
          setBankStatus(data);
          break;
        }

        case "merchants": {
          const res = await fetch("/api/merchants");
          const data = await res.json();
          setMerchants(data.merchants ?? []);
          break;
        }

        case "dashboard": {
          const ledgerRes = await fetch("/api/ledger?limit=5000");
          const ledgerData = await ledgerRes.json();
          setLedger(ledgerData.entries ?? []);

          const peopleRes = await fetch("/api/people");
          const peopleData = await peopleRes.json();
          setPeople(peopleData.people ?? []);
          break;
        }

        case "history": {
          const res = await fetch("/api/ledger?limit=5000");
          const data = await res.json();
          setLedger(data.entries ?? []);
          break;
        }

        case "failures": {
          const res = await fetch("/api/payments/failures");
          const data = await res.json();
          setFailures(data);
          break;
        }

        case "recovery":
        case "recovery-metrics":
        case "recovery-audit": {
          const metricsRes = await fetch("/api/recovery/metrics");
          const metricsData = await metricsRes.json();
          setRecoveryMetrics(metricsData);

          const actionsRes = await fetch("/api/recovery/actions?limit=5000");
          const actionsData = await actionsRes.json();
          setRecoveryActions(actionsData?.actions ?? []);
          break;
        }

        case "sara-attempts": {
          // SaraAttemptsView fetches its own lifetime SARA retry data
          break;
        }
      }
    } catch (e) {
      console.error(`Failed to fetch data for ${tab}:`, e);
    } finally {
      setLoading(false);
    }
  }, [refreshTrigger]);

  // Fetch data when tab changes
  useEffect(() => {
    fetchDataForTab(activeTab);
  }, [activeTab, fetchDataForTab, refreshTrigger]);

  // Refresh function to trigger data refetch
  const refreshData = () => {
    setRefreshTrigger((prev) => prev + 1);
  };

  // Render the active tab
  const renderTab = () => {
    switch (activeTab) {
      case "dashboard":
        return (
          <Dashboard
            people={people}
            ledger={ledger}
            simulation={simulation}
            bankStatus={bankStatus}
            loading={loading}
            onRefresh={refreshData}
            setActiveTab={setActiveTab}
          />
        );

      case "simulation":
        return <SimulationRunner simulation={simulation} onRefresh={refreshData} onComparisonComplete={(report) => { setComparisonReport(report); setActiveTab("comparison"); }} />;

      case "comparison":
        return <ComparisonView initialReport={comparisonReport} onReport={setComparisonReport} />;

      case "people":
        return (
          <PeopleView
            people={people}
            loading={loading}
            onRefresh={refreshData}
          />
        );

      case "transactions":
        return (
          <TransactionsView
            ledger={ledger}
            loading={loading}
            onRefresh={refreshData}
          />
        );

      case "bank":
        return <BankStatus bankStatus={bankStatus} loading={loading} onRefresh={refreshData} />;

      case "history":
        return <PerPersonHistory ledger={ledger} loading={loading} onRefresh={refreshData} />;

      case "merchants":
        return (
          <MerchantsTable
            merchants={merchants}
            loading={loading}
            onRefresh={refreshData}
          />
        );

      case "revenue":
        return (
          <MerchantRevenueView
            merchants={merchants}
            loading={loading}
            onRefresh={refreshData}
          />
        );

      case "failures":
        return (
          <FailuresView
            failures={failures}
            loading={loading}
            onRefresh={refreshData}
          />
        );

      case "recovery":
        return (
          <RecoveryView
            metrics={recoveryMetrics}
            actions={recoveryActions}
            loading={loading}
            onRefresh={refreshData}
          />
        );

      case "recovery-metrics":
        return (
          <RecoveryView
            metrics={recoveryMetrics}
            actions={recoveryActions}
            loading={loading}
            onRefresh={refreshData}
            detailedMetrics={true}
          />
        );

      case "recovery-audit":
        return (
          <RecoveryView
            metrics={recoveryMetrics}
            actions={recoveryActions}
            loading={loading}
            onRefresh={refreshData}
            auditMode={true}
          />
        );

      case "sara-attempts":
        return (
          <SaraAttemptsView
            onRefresh={refreshData}
            experimentId={comparisonReport?.experiment_id}
          />
        );

      default:
        return <Dashboard
          people={people}
          ledger={ledger}
          simulation={simulation}
          bankStatus={bankStatus}
          loading={loading}
          onRefresh={refreshData}
          setActiveTab={setActiveTab}
        />;
    }
  };

  return (
    <div className="app">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        currentDay={simulation.currentDayDisplay}
        currentDate={simulation.currentDate}
        isRunning={simulation.isRunning}
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
      />
      <main className={`main-content ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
        <header className="page-header">
          <h1 className="page-title">{TAB_TITLES[activeTab] || "Dashboard"}</h1>
        </header>
        <div className="tab-content-wrapper">
          {renderTab()}
        </div>
      </main>
    </div>
  );
}

export default App;
