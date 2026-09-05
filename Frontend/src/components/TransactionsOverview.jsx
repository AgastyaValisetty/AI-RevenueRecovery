import React from "react";
import { BookOpen, Inbox, ArrowDownLeft, ArrowUpRight } from "./ui/icons";
import ScrollFade from "./ui/ScrollFade";
import "./TransactionsOverview.css";

const TransactionsOverview = () => {
  const [transactions, setTransactions] = React.useState([]);
  const [eventTypes, setEventTypes] = React.useState({});

  React.useEffect(() => {
    fetch("/api/ledger")
      .then((res) => res.json())
      .then((data) => {
        setTransactions(data.entries ?? []);
        const types = {};
        (data.entries ?? []).forEach((e) => {
          types[e.event_type] = (types[e.event_type] || 0) + 1;
        });
        setEventTypes(types);
      })
      .catch((e) => console.error("Failed to fetch ledger:", e));
  }, []);

  const totalCost = transactions
    .filter((e) => e.event_type === "LIVING_COST")
    .reduce((sum, e) => sum + parseFloat(e.amount || 0), 0);

  const totalTransactions = transactions.length;

  return (
    <ScrollFade className="animate-scroll-fade">
      <div className="transactions-panel">
        <div className="transactions-header">
          <div className="panel-title-group">
            <BookOpen size={18} />
            <span className="panel-title">Transactions Overview</span>
          </div>
        </div>

        <div className="overview-stats">
          <div className="stat">
            <span>Total Transactions</span>
            <span>{totalTransactions}</span>
          </div>
          <div className="stat">
            <span>Total Living Cost</span>
            <span className="currency">₹{totalCost.toLocaleString()}</span>
          </div>
        </div>

        <div className="event-types">
          <span>By Type:</span>
          {Object.entries(eventTypes).map(
            ([type, count]) => (
              <span key={type} className="event-type-item">
                <ArrowDownLeft size={10} />
                {type}: {count}
              </span>
            )
          )}
        </div>

        <div className="recent-transactions">
          <div className="recent-header">
            <BookOpen size={14} />
            <span>Recent:</span>
          </div>
          <ul>
            {transactions
              .slice(0, 10)
              .map((e, i) => (
                <li key={i}>
                  <span>
                    <ArrowDownLeft size={11} className="event-icon credit" />
                    <strong>{e.event_type}:</strong> ₹{e.amount}
                  </span>
                  <span className="direction-label">
                    {e.from_account_id ? "from" : "to"}
                  </span>
                </li>
              ))}
            {transactions.length === 0 && (
              <li>
                <Inbox size={16} />
                <span>No transactions</span>
              </li>
            )}
          </ul>
        </div>
      </div>
    </ScrollFade>
  );
};

export default TransactionsOverview;
