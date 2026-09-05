import React from "react";
import { Play, Pause } from "./ui/icons";
import ScrollFade from "./ui/ScrollFade";
import "./SimulationControls.css";

const SimulationControls = ({ isRunning, setIsRunning, currentDay, setCurrentDay }) => {
  const toggleSimulation = async () => {
    setIsRunning(!isRunning);
  };

  return (
    <ScrollFade className="animate-scroll-fade">
      <div className="sim-controls">
        <div className="sim-controls-header">
          <h3>Simulation Control</h3>
        </div>

        <div className="toggle-btn">
          <button
            className={`btn ${isRunning ? 'btn-secondary' : 'btn-primary'}`}
            onClick={toggleSimulation}
          >
            {isRunning ? (
              <>
                <Pause size={14} />
                <span>Pause</span>
              </>
            ) : (
              <>
                <Play size={14} />
                <span>Start</span>
              </>
            )}
          </button>
        </div>

        <div className="day-indicator">
          <span className="day-label">Day:</span>
          <span className="day-value">{currentDay}</span>
        </div>
      </div>
    </ScrollFade>
  );
};

export default SimulationControls;
