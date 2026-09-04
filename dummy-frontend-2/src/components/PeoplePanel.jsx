import React from "react";
import { Users, Search } from "./ui/icons";
import { money } from "../utils/format";
import ScrollFade from "./ui/ScrollFade";
import "./PeoplePanel.css";

const PeoplePanel = ({ onSelectPerson }) => {
  const [people, setPeople] = React.useState([]);
  const [search, setSearch] = React.useState("");

  React.useEffect(() => {
    fetch("/api/people")
      .then((res) => res.json())
      .then((data) => {
        setPeople(data.people ?? []);
      })
      .catch((e) => console.error("Failed to fetch people:", e));
  }, [search]);

  const filteredPeople = people.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <ScrollFade className="animate-scroll-fade">
      <div className="people-panel">
        <div className="people-panel-header">
          <h3>People ({people.length})</h3>
          <div className="search-input-wrapper">
            <Search size={14} />
            <input
              type="text"
              placeholder="Search people..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="search-input"
            />
          </div>
        </div>
        <div className="people-list">
          {filteredPeople.map((p) => (
            <div
              key={p.person_id}
              className="person-card"
              onClick={() => onSelectPerson && onSelectPerson(p.person_id)}
            >
              <span className="person-name">
                {p.name} ({p.age})
              </span>
              <span className="person-meta">
                Salary: ₹{money(p.salary)} · Bal: ₹{money(p.current_balance || 0)}
              </span>
            </div>
          ))}
          {filteredPeople.length === 0 && <p className="empty-msg">No people found</p>}
        </div>
      </div>
    </ScrollFade>
  );
};

export default PeoplePanel;
