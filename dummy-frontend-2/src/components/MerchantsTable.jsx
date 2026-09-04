import React from 'react';
import { Storefront, ShoppingBag, MusicNote, FilmSlate, ShoppingCart, CreditCard } from './ui/icons';
import ScrollFade from './ui/ScrollFade';

const getMerchantIcon = (name) => {
  const lower = name.toLowerCase();
  if (lower.includes('spotifly')) return MusicNote;
  if (lower.includes('petflix')) return FilmSlate;
  if (lower.includes('amazin')) return ShoppingBag;
  return Storefront;
};

export default function MerchantsTable({ merchants, loading }) {
  return (
    <ScrollFade className="animate-scroll-fade">
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <Storefront size={18} />
            <span className="panel-title">Ecosystem Merchants &amp; Billing Models</span>
            <span className="badge-count">{merchants?.length ?? 0} Partners</span>
          </div>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Merchant Name</th>
                <th>Type / Billing Mode</th>
                <th>Settlement Bank</th>
                <th>Merchant ID</th>
              </tr>
            </thead>
            <tbody>
              {!merchants || merchants.length === 0 ? (
                <tr>
                  <td colSpan="4">
                    <div className="empty-state">
                      <Storefront size={32} />
                      <p>{loading ? 'Loading merchants...' : 'No merchants seeded yet. Run the simulation.'}</p>
                    </div>
                  </td>
                </tr>
              ) : (
                merchants.map((merchant) => {
                  const Icon = getMerchantIcon(merchant.name);
                  const isSubOnly = merchant.merchant_type === 'SUBSCRIPTION_ONLY';
                  return (
                    <tr key={merchant.merchant_id}>
                      <td>
                        <div className="merchant-name-cell">
                          <div className={`merchant-icon-wrapper ${isSubOnly ? 'merchant-sub' : 'merchant-mixed'}`}>
                            <Icon size={16} />
                          </div>
                          <span>{merchant.name}</span>
                        </div>
                      </td>
                      <td>
                        <span className={`tag-badge ${isSubOnly ? 'tag-stop' : 'tag-link'}`}>
                          {merchant.merchant_type}
                        </span>
                      </td>
                      <td className="bank-cell">
                        <CreditCard size={14} />
                        <span>RupeeBank</span>
                      </td>
                      <td className="mono-cell">{merchant.merchant_id}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </ScrollFade>
  );
}
