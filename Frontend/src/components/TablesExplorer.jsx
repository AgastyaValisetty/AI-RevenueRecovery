import React, { useState } from 'react';
import { Database, Table, Key, Layers, Hash } from './ui/icons';
import ScrollFade from './ui/ScrollFade';

const DATA_TYPE_LABELS = {
  UUID: 'UUID',
  VARCHAR: 'VARCHAR',
  NUMERIC: 'NUMERIC',
  TIMESTAMPTZ: 'TIMESTAMPTZ',
  DATE: 'DATE',
  INTEGER: 'INTEGER',
  TEXT: 'TEXT',
  JSONB: 'JSONB',
};

export default function TablesExplorer({ status }) {
  const [selectedTable, setSelectedTable] = useState('ledger_entries');

  const tables = [
    {
      name: 'ledger_entries',
      title: 'Ledger Entries',
      category: 'Accounting & Balances',
      liveCount: status?.ledger_entries ?? 0,
      description: 'Immutable double-entry financial ledger recording salary deposits, living expense deductions, and settled/failed payment attempts.',
      columns: [
        { name: 'entry_id', type: 'UUID', isPk: true, desc: 'Primary Key' },
        { name: 'event_type', type: 'VARCHAR(32)', desc: 'SALARY_DEPOSIT | LIVING_COST | PAYMENT_SETTLED | PAYMENT_FAILED' },
        { name: 'from_account_id', type: 'UUID (FK)', desc: 'Source Bank Account ID' },
        { name: 'to_account_id', type: 'UUID (FK)', desc: 'Destination Bank Account ID' },
        { name: 'amount', type: 'NUMERIC(12, 2)', desc: 'Monetary transaction value' },
        { name: 'related_attempt_id', type: 'VARCHAR(64) (FK)', desc: 'Reference to payment_attempts' },
        { name: 'related_subscription_id', type: 'UUID (FK)', desc: 'Reference to subscriptions' },
        { name: 'simulation_timestamp', type: 'TIMESTAMPTZ', desc: 'Simulated clock execution time' },
        { name: 'metadata_json', type: 'JSONB', desc: 'Category, day type, percentage breakdown' },
        { name: 'created_at', type: 'TIMESTAMPTZ', desc: 'Record insertion time' },
      ],
    },
    {
      name: 'persons',
      title: 'Persons (Population)',
      category: 'Core Entities',
      liveCount: status?.people ?? 0,
      description: 'Synthetic population demographic, income properties, and spending behavior profiles.',
      columns: [
        { name: 'person_id', type: 'UUID', isPk: true, desc: 'Primary Key' },
        { name: 'name', type: 'VARCHAR(128)', desc: 'Full Name' },
        { name: 'age', type: 'INTEGER', desc: 'Age (18 - 80)' },
        { name: 'salary', type: 'NUMERIC(12, 2)', desc: 'Monthly Salary (₹30,000 - ₹500,000)' },
        { name: 'salary_deposit_day', type: 'INTEGER', desc: 'Day of month salary is credited' },
        { name: 'spending_profile_category', type: 'VARCHAR(64)', desc: 'student | young_professional | family | high_income | retired' },
        { name: 'spending_profile_json', type: 'JSONB', desc: 'Base percentage & category weights' },
        { name: 'payment_preferences_json', type: 'JSONB', desc: 'Weights for UPI, CARD, NETBANKING' },
        { name: 'primary_bank_id', type: 'UUID (FK)', desc: 'Linked to banks table' },
        { name: 'primary_account_id', type: 'UUID (FK)', desc: 'Linked to bank_accounts table' },
      ],
    },
    {
      name: 'subscriptions',
      title: 'Subscriptions',
      category: 'Recurring Billing',
      liveCount: status?.subscriptions ?? 0,
      description: 'Recurring monthly subscriptions linking customers to merchant products.',
      columns: [
        { name: 'subscription_id', type: 'UUID', isPk: true, desc: 'Primary Key' },
        { name: 'person_id', type: 'UUID (FK)', desc: 'Subscriber ID' },
        { name: 'merchant_id', type: 'UUID (FK)', desc: 'Merchant ID' },
        { name: 'product_id', type: 'UUID (FK)', desc: 'Product ID' },
        { name: 'amount', type: 'NUMERIC(12, 2)', desc: 'Recurring billing amount' },
        { name: 'billing_cycle', type: 'VARCHAR(16)', desc: 'MONTHLY' },
        { name: 'status', type: 'VARCHAR(32)', desc: 'ACTIVE | PENDING | FAILED | CANCELLED' },
        { name: 'next_billing_date', type: 'DATE', desc: 'Next scheduled due date' },
        { name: 'consecutive_failures', type: 'INTEGER', desc: 'Failure counter for recovery intervention' },
      ],
    },
    {
      name: 'payment_intents',
      title: 'Payment Intents',
      category: 'Transaction Pipeline',
      liveCount: status?.payment_intents ?? 0,
      description: 'Queued transaction intents created during subscription billing cycles.',
      columns: [
        { name: 'intent_id', type: 'UUID', isPk: true, desc: 'Primary Key' },
        { name: 'person_id', type: 'UUID (FK)', desc: 'Customer' },
        { name: 'merchant_id', type: 'UUID (FK)', desc: 'Merchant' },
        { name: 'product_id', type: 'UUID (FK)', desc: 'Product' },
        { name: 'amount', type: 'NUMERIC(12, 2)', desc: 'Transaction charge amount' },
        { name: 'payment_method', type: 'VARCHAR(32)', desc: 'UPI | CARD | NETBANKING' },
        { name: 'status', type: 'VARCHAR(32)', desc: 'PENDING | PROCESSING | COMPLETED | FAILED' },
        { name: 'expires_at', type: 'TIMESTAMPTZ', desc: 'Intent expiry cutoff' },
      ],
    },
    {
      name: 'merchants',
      title: 'Merchants',
      category: 'Core Entities',
      liveCount: status?.merchants ?? 0,
      description: 'Ecosystem merchants with business models.',
      columns: [
        { name: 'merchant_id', type: 'UUID', isPk: true, desc: 'Primary Key' },
        { name: 'name', type: 'VARCHAR(64)', desc: 'Business brand name' },
        { name: 'merchant_type', type: 'VARCHAR(32)', desc: 'SUBSCRIPTION_ONLY | MIXED' },
        { name: 'settlement_bank_id', type: 'UUID (FK)', desc: 'Target bank for credit settlement' },
      ],
    },
    {
      name: 'banks',
      title: 'Banks',
      category: 'Banking System',
      liveCount: 1,
      description: 'Bank institutions with state machines.',
      columns: [
        { name: 'bank_id', type: 'UUID', isPk: true, desc: 'Primary Key' },
        { name: 'name', type: 'VARCHAR(64)', desc: 'Bank Name' },
        { name: 'authorization_success_rate', type: 'NUMERIC(6, 2)', desc: 'Base success probability' },
        { name: 'timeout_rate', type: 'NUMERIC(6, 2)', desc: 'Timeout rate' },
        { name: 'issuer_decline_rate', type: 'NUMERIC(6, 2)', desc: 'Issuer decline rate' },
        { name: 'network_error_rate', type: 'NUMERIC(6, 2)', desc: 'Network error rate' },
        { name: 'current_state', type: 'VARCHAR(32)', desc: 'NORMAL | PEAK | DEGRADED | OUTAGE' },
      ],
    },
    {
      name: 'bank_accounts',
      title: 'Bank Accounts',
      category: 'Banking System',
      liveCount: status?.people ?? 0,
      description: 'Accounts holding funds for people and merchants.',
      columns: [
        { name: 'account_id', type: 'UUID', isPk: true, desc: 'Primary Key' },
        { name: 'person_id', type: 'UUID (FK)', desc: 'Owner person ID' },
        { name: 'bank_id', type: 'UUID (FK)', desc: 'Bank institution ID' },
      ],
    },
    {
      name: 'products',
      title: 'Products',
      category: 'Catalog',
      liveCount: 8,
      description: 'Merchant items and recurring subscription tiers.',
      columns: [
        { name: 'product_id', type: 'UUID', isPk: true, desc: 'Primary Key' },
        { name: 'merchant_id', type: 'UUID (FK)', desc: 'Merchant owner' },
        { name: 'name', type: 'VARCHAR(128)', desc: 'Product Title' },
        { name: 'price', type: 'NUMERIC(12, 2)', desc: 'List price' },
        { name: 'product_type', type: 'VARCHAR(32)', desc: 'SUBSCRIPTION | ONE_TIME' },
      ],
    },
    {
      name: 'payment_attempts',
      title: 'Payment Attempts',
      category: 'Gateway Logs',
      liveCount: 0,
      description: 'LazerPay payment gateway execution attempts.',
      columns: [
        { name: 'attempt_id', type: 'VARCHAR(64)', isPk: true, desc: 'Primary Key' },
        { name: 'intent_id', type: 'UUID (FK)', desc: 'Linked payment intent' },
        { name: 'attempt_number', type: 'INTEGER', desc: 'Retry ordinal index' },
        { name: 'status', type: 'VARCHAR(32)', desc: 'INITIATED | ROUTING | AUTHORIZED | SETTLED | FAILED' },
        { name: 'idempotency_key', type: 'VARCHAR(128)', desc: 'Duplicate protection key' },
        { name: 'failure_code', type: 'VARCHAR(64)', desc: 'INSUFFICIENT_FUNDS | TIMEOUT | HARD_DECLINE' },
      ],
    },
    {
      name: 'recovery_actions',
      title: 'Recovery Actions',
      category: 'AI Recovery Agent',
      liveCount: 0,
      description: 'Autonomous recovery decisions and dynamic retry schedules.',
      columns: [
        { name: 'action_id', type: 'UUID', isPk: true, desc: 'Primary Key' },
        { name: 'related_attempt_id', type: 'VARCHAR(64) (FK)', desc: 'Failed attempt target' },
        { name: 'action_type', type: 'VARCHAR(32)', desc: 'RETRY | SEND_LINK | WAITING_SALARY' },
        { name: 'reason', type: 'TEXT', desc: 'AI decision rationale' },
        { name: 'outcome', type: 'VARCHAR(32)', desc: 'RECOVERED | PERMANENT_FAIL' },
      ],
    },
  ];

  const current = tables.find((t) => t.name === selectedTable) || tables[0];

  return (
    <ScrollFade className="animate-scroll-fade">
      <div className="tables-explorer-layout">
        <div className="panel tables-sidebar">
          <div className="panel-header">
            <div className="panel-title-group">
              <Layers size={16} />
              <span className="panel-title">Schema Tables ({tables.length})</span>
            </div>
          </div>
          <div className="tables-nav">
            {tables.map((t) => (
              <button
                key={t.name}
                onClick={() => setSelectedTable(t.name)}
                className={`table-nav-item ${selectedTable === t.name ? 'active' : ''}`}
              >
                <div className="table-nav-label">
                  <Table size={14} />
                  <span>{t.name}</span>
                </div>
                <span className="table-nav-count">{t.liveCount}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="panel tables-detail">
          <div className="panel-header">
            <div>
              <div className="panel-title mono-cell" style={{ fontSize: '16px' }}>Table: {current.name}</div>
              <div className="text-muted" style={{ fontSize: '12px', marginTop: '2px' }}>
                {current.description}
              </div>
            </div>
            <div className="badge-count">{current.liveCount.toLocaleString()} Live Rows</div>
          </div>

          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Column Name</th>
                  <th>SQL Data Type</th>
                  <th>Constraint / Key</th>
                  <th>Field Description</th>
                </tr>
              </thead>
              <tbody>
                {current.columns.map((col) => (
                  <tr key={col.name}>
                    <td className="mono-cell primary-cell">{col.name}</td>
                    <td className="mono-cell data-type-cell">{col.type}</td>
                    <td>
                      {col.isPk ? (
                        <span className="tag-badge tag-run" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                          <Key size={11} />
                          <span>PRIMARY KEY</span>
                        </span>
                      ) : col.type.includes('(FK)') ? (
                        <span className="tag-badge tag-link">
                          FOREIGN KEY
                        </span>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td className="text-secondary">{col.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </ScrollFade>
  );
}
