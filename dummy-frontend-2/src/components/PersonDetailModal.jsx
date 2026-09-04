import React, { useEffect, useState } from 'react';
import { X, User, ShieldCheck } from './ui/icons';
import { fetchPersonDetail } from '../api';
import { money } from '../utils/format';

export default function PersonDetailModal({ personId, onClose }) {
  const [person, setPerson] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!personId) return;
    setLoading(true);
    setError(null);
    fetchPersonDetail(personId)
      .then((data) => setPerson(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [personId]);

  if (!personId) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-title">
            <div className="person-icon-wrapper">
              <User size={16} />
            </div>
            <div>
              <div className="modal-name">
                {loading ? 'Fetching Person...' : person?.name}
              </div>
              <div className="modal-person-id">{personId}</div>
            </div>
          </div>
          <button className="btn btn-outline btn-icon" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="modal-body">
          {loading && (
            <div className="empty-state">
              <div className="spinner" style={{ margin: '0 auto 12px auto' }}></div>
              <p>Querying Postgres ledger and account balances…</p>
            </div>
          )}

          {error && (
            <div className="toast error" style={{ position: 'static', margin: '0 0 16px 0' }}>
              <span>{error}</span>
            </div>
          )}

          {person && (
            <>
              <div className="detail-grid">
                <div className="detail-item">
                  <div className="detail-label">Current Ledger Balance</div>
                  <div className="detail-value currency">{money(person.current_balance)}</div>
                </div>

                <div className="detail-item">
                  <div className="detail-label">Monthly Gross Salary</div>
                  <div className="detail-value currency">{money(person.salary)}</div>
                </div>

                <div className="detail-item">
                  <div className="detail-label">Salary Deposit Day</div>
                  <div className="detail-value">{person.salary_deposit_day}th of every month</div>
                </div>

                <div className="detail-item">
                  <div className="detail-label">Age &amp; Category</div>
                  <div className="detail-value" style={{ textTransform: 'capitalize' }}>
                    {person.age} yrs • {person.spending_profile_category.replace('_', ' ')}
                  </div>
                </div>
              </div>

              <div className="person-profile-properties">
                <div className="profile-properties-header">
                  <ShieldCheck size={14} />
                  <span>Simulation Profile Properties</span>
                </div>
                <p className="text-muted">
                  This person's daily living costs are dynamically computed based on their{' '}
                  <strong className="text-primary">{person.spending_profile_category}</strong> profile. When recurring subscription payments fall due, their primary bank account at{' '}
                  <strong className="text-primary">RupeeBank</strong> will be billed. If their balance drops below the charge amount, an{' '}
                  <strong className="text-muted">INSUFFICIENT_FUNDS</strong> failure will be logged to trigger the recovery agent.
                </p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
