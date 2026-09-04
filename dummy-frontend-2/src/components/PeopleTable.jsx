import React, { useState, useMemo } from 'react';
import { Search, Eye, ChevronLeft, ChevronRight, Users, Faders } from './ui/icons';
import ScrollFade from './ui/ScrollFade';

export default function PeopleTable({ people, onSelectPerson, loading }) {
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('ALL');
  const [currentPage, setCurrentPage] = useState(1);
  const pageSize = 15;

  const categories = useMemo(() => {
    if (!people || people.length === 0) return [];
    const set = new Set(people.map((p) => p.spending_profile_category));
    return Array.from(set);
  }, [people]);

  const filteredPeople = useMemo(() => {
    if (!people) return [];
    return people.filter((p) => {
      const matchSearch =
        p.name.toLowerCase().includes(search.toLowerCase()) ||
        p.person_id.toLowerCase().includes(search.toLowerCase());
      const matchCategory =
        categoryFilter === 'ALL' || p.spending_profile_category === categoryFilter;
      return matchSearch && matchCategory;
    });
  }, [people, search, categoryFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredPeople.length / pageSize));
  const paginatedPeople = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredPeople.slice(start, start + pageSize);
  }, [filteredPeople, currentPage]);

  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= totalPages) {
      setCurrentPage(newPage);
    }
  };

  const getProfileClass = (category) => {
    switch (category) {
      case 'student':
        return 'tag-student';
      case 'young_professional':
        return 'tag-young_professional';
      case 'family':
        return 'tag-family';
      case 'high_income':
        return 'tag-high_income';
      case 'retired':
        return 'tag-retired';
      default:
        return '';
    }
  };

  return (
    <ScrollFade className="animate-scroll-fade">
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title-group">
            <Users size={18} />
            <span className="panel-title">Simulated People Directory</span>
            <span className="badge-count">{filteredPeople.length} Records</span>
          </div>

          <div className="controls-bar">
            <div className="search-input-wrapper">
              <Search size={15} />
              <input
                type="text"
                placeholder="Search by name or UUID..."
                className="search-input"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setCurrentPage(1);
                }}
              />
            </div>

            <select
              className="select-filter"
              value={categoryFilter}
              onChange={(e) => {
                setCategoryFilter(e.target.value);
                setCurrentPage(1);
              }}
            >
              <option value="ALL">All Spending Profiles</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {c.replace('_', ' ')}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="table-responsive">
          <table className="data-table">
            <thead>
              <tr>
                <th>Person Name</th>
                <th>Age</th>
                <th>Monthly Salary</th>
                <th>Salary Deposit Day</th>
                <th>Spending Profile</th>
                <th>Current Balance</th>
                <th>Person ID</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {paginatedPeople.length === 0 ? (
                <tr>
                  <td colSpan="8">
                    <div className="empty-state">
                      <Users size={32} />
                      <p>{loading ? 'Loading people records...' : 'No simulation people found. Run the simulation to generate population.'}</p>
                    </div>
                  </td>
                </tr>
              ) : (
                paginatedPeople.map((person) => (
                  <tr
                    key={person.person_id}
                    onClick={() => onSelectPerson(person.person_id)}
                  >
                    <td className="primary-cell">{person.name}</td>
                    <td>{person.age} yrs</td>
                    <td className="currency mono-cell">
                      ₹{Number(person.salary).toLocaleString('en-IN')}
                    </td>
                    <td>Day {person.salary_deposit_day} of month</td>
                    <td>
                      <span
                        className={`tag-badge ${getProfileClass(
                          person.spending_profile_category
                        )}`}
                      >
                        {person.spending_profile_category.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="currency mono-cell">
                      ₹{Number(person.current_balance || 0).toLocaleString()}
                    </td>
                    <td className="mono-cell">
                      {person.person_id.slice(0, 8)}...
                    </td>
                    <td>
                      <button
                        className="btn btn-outline btn-sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectPerson(person.person_id);
                        }}
                      >
                        <Eye size={12} />
                        <span>Inspect</span>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {filteredPeople.length > 0 && (
          <div className="pagination">
            <div className="page-info">
              Showing {(currentPage - 1) * pageSize + 1} to{' '}
              {Math.min(currentPage * pageSize, filteredPeople.length)} of{' '}
              {filteredPeople.length} people
            </div>
            <div className="page-actions">
              <button
                className="btn btn-secondary"
                disabled={currentPage === 1}
                onClick={() => handlePageChange(currentPage - 1)}
              >
                <ChevronLeft size={14} />
              </button>
              <span className="page-number">
                {currentPage} / {totalPages}
              </span>
              <button
                className="btn btn-secondary"
                disabled={currentPage === totalPages}
                onClick={() => handlePageChange(currentPage + 1)}
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </ScrollFade>
  );
}
