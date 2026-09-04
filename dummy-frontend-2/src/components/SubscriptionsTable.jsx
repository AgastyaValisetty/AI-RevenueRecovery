import React, { useState, useMemo } from 'react';
import { Repeat, Search, CheckCircle2, Calendar } from './ui/icons';
import ScrollFade from './ui/ScrollFade';
import { money } from '../utils/format';

export default function SubscriptionsTable({ people, merchants, status, rawSubscriptions, loading }) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');

  const peopleMap = useMemo(() => {
    const map = new Map();
    if (people) people.forEach((p) => map.set(p.person_id, p.name));
    return map;
  }, [people]);

  const merchantMap = useMemo(() => {
    const map = new Map();
    if (merchants) merchants.forEach((m) => map.set(m.merchant_id, m.name));
    return map;
  }, [merchants]);

  const subscriptions = useMemo(() => {
    if (rawSubscriptions && Array.isArray(rawSubscriptions) && rawSubscriptions.length > 0) {
      return rawSubscriptions.map((s) => ({
        sub_id: s.subscription_id,
        person_name: peopleMap.get(s.person_id) || `Person ${s.person_id.slice(0, 6)}...`,
        merchant_name: merchantMap.get(s.merchant_id) || 'Merchant Partner',
        product_name: s.billing_cycle === 'MONTHLY' ? 'Monthly Recurring Plan' : 'Standard Tier',
        amount: Number(s.amount),
        billing_cycle: s.billing_cycle,
        status: s.status,
        consecutive_failures: s.consecutive_failures || 0,
        next_billing_date: s.next_billing_date,
      }));
    }

    if (!people || people.length === 0) return [];

    const merchantPlans = [
      { name: 'Spotifly Monthly', merchant: 'Spotifly', price: 119.00 },
      { name: 'Petflix Monthly', merchant: 'Petflix', price: 199.00 },
      { name: 'Amazin Prime', merchant: 'Amazin', price: 599.00 },
      { name: 'Flip Cartel Plus', merchant: 'Flip Cartel', price: 499.00 },
    ];

    const currDate = status?.current_date ? new Date(status.current_date) : new Date(2024, 0, 1);
    const list = [];

    people.forEach((p, pIdx) => {
      const plan1 = merchantPlans[pIdx % merchantPlans.length];
      const plan2 = merchantPlans[(pIdx + 1) % merchantPlans.length];

      const d1 = new Date(currDate);
      d1.setDate(d1.getDate() + ((pIdx % 28) + 1));
      const d2 = new Date(currDate);
      d2.setDate(d2.getDate() + (((pIdx + 5) % 28) + 1));

      list.push({
        sub_id: `sub_${p.person_id.slice(0, 6)}_01`,
        person_name: p.name,
        merchant_name: plan1.merchant,
        product_name: plan1.name,
        amount: plan1.price,
        billing_cycle: 'MONTHLY',
        status: pIdx % 12 === 0 ? 'FAILED' : 'ACTIVE',
        consecutive_failures: pIdx % 12 === 0 ? 3 : 0,
        next_billing_date: d1.toISOString().slice(0, 11).split('T')[0],
      });

      list.push({
        sub_id: `sub_${p.person_id.slice(0, 6)}_02`,
        person_name: p.name,
        merchant_name: plan2.merchant,
        product_name: plan2.name,
        amount: plan2.price,
        billing_cycle: 'MONTHLY',
        status: 'ACTIVE',
        consecutive_failures: 0,
        next_billing_date: d2.toISOString().slice(0, 11).split('T')[0],
      });
    });

    return list;
  }, [people, merchants, rawSubscriptions, peopleMap, merchantMap, status]);

  const filtered = useMemo(() => {
    return subscriptions.filter((s) => {
      const matchSearch =
        s.person_name.toLowerCase().includes(search.toLowerCase()) ||
        s.merchant_name.toLowerCase().includes(search.toLowerCase()) ||
        s.product_name.toLowerCase().includes(search.toLowerCase()) ||
        s.sub_id.toLowerCase().includes(search.toLowerCase());
      const matchStatus = statusFilter === 'ALL' || s.status === statusFilter;
      return matchSearch && matchStatus;
    });
  }, [subscriptions, search, statusFilter]);

  return (
    <ScrollFade className="animate-scroll-fade">
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <Repeat size={18} />
            <span className="panel-title">Active Recurring Subscriptions</span>
            <span className="badge-count">
              {status?.subscriptions ? `${status.subscriptions} Total` : `${filtered.length} Subscriptions`}
            </span>
          </div>

          <div className="controls-bar">
            <div className="search-input-wrapper">
              <Search size={15} />
              <input
                type="text"
                placeholder="Search by subscriber or product..."
                className="search-input"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <select
              className="select-filter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="ALL">All Statuses</option>
              <option value="ACTIVE">Active Only</option>
              <option value="FAILED">Failed Only</option>
            </select>
          </div>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Subscription ID</th>
                <th>Subscriber Name</th>
                <th>Merchant &amp; Plan</th>
                <th>Monthly Amount</th>
                <th>Billing Status</th>
                <th>Next Due Date</th>
                <th>Failures</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <tr>
                  <td colSpan="7">
                    <div className="empty-state">
                      <Repeat size={32} />
                      <p>{loading ? 'Loading subscriptions...' : 'No subscriptions recorded.'}</p>
                    </div>
                  </td>
                </tr>
              ) : (
                filtered.slice(0, 100).map((sub) => (
                  <tr key={sub.sub_id}>
                    <td className="mono-cell">{sub.sub_id.slice(0, 13)}…</td>
                    <td className="primary-cell">{sub.person_name}</td>
                    <td>
                      <div className="subscription-plan-name">{sub.product_name}</div>
                      <div className="subscription-merchant text-muted">{sub.merchant_name}</div>
                    </td>
                    <td className="currency">{money(sub.amount)}</td>
                    <td>
                      <span className={`tag-badge ${sub.status === 'ACTIVE' ? 'tag-success' : 'tag-failed'}`}>
                        {sub.status}
                      </span>
                    </td>
                    <td className="mono-cell timestamp-cell">{sub.next_billing_date}</td>
                    <td>
                      {sub.consecutive_failures > 0 ? (
                        <span className="text-red mono-cell">{sub.consecutive_failures} fails</span>
                      ) : (
                        <span className="text-muted mono-cell">0</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </ScrollFade>
  );
}
