import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import LiveMap from '../components/LiveMap';
import ReviewQueue from '../components/ReviewQueue';
import ReportModal from '../components/ReportModal';
import client from '../api/client';
import { useDisasterSocket } from '../hooks/useDisasterSocket';

export default function Dashboard() {
  const [health, setHealth] = useState({ connected: false, latency: 0 });
  const [showReportModal, setShowReportModal] = useState(false);
  const [stats, setStats] = useState({ needs: 0, resources: 0 });
  // Increment to trigger child component refreshes on real-time events
  const [refreshTick, setRefreshTick] = useState(0);
  const navigate = useNavigate();


  useEffect(() => {
    if (!localStorage.getItem('token')) {
      navigate('/login');
      return;
    }

    const checkHealth = async () => {
      try {
        const start = Date.now();
        await client.get('/health');
        const latency = Date.now() - start;
        setHealth({ connected: true, latency });
      } catch (err) {
        setHealth(prev => ({ ...prev, connected: false }));
        if (err.response?.status === 401) {
          localStorage.removeItem('token');
          navigate('/login');
        }
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, [navigate]);

  // Real-time WebSocket events — trigger child refreshes on data changes
  const handleWsEvent = useCallback((payload) => {
    const refreshEvents = ['NEED_UPDATED', 'NEED_PROCESSING', 'NEED_ERROR', 'PLAN_READY', 'NEED_RESUMING'];
    if (refreshEvents.includes(payload.event)) {
      setRefreshTick(t => t + 1);
    }
  }, []);

  const { connected: wsConnected } = useDisasterSocket(handleWsEvent);

  return (
    <div className="h-screen w-full flex flex-col overflow-hidden bg-bg-base text-text-primary">
      {/* HEADER BAR - 48px fixed */}
      <header className="h-12 shrink-0 border-b border-border-subtle bg-bg-surface flex items-center justify-between px-4">
        <div className="flex items-center gap-4 w-1/3">
          <h1 className="text-sm font-semibold tracking-wide text-text-primary">
            DISASTER COORDINATOR
          </h1>
        </div>
        
        <div className="flex items-center justify-center gap-2 w-1/3 text-xs">
          <div className={`w-2 h-2 rounded-full ${health.connected ? 'bg-success' : 'bg-critical'}`}></div>
          <span className="font-medium text-text-secondary">
            {health.connected ? `SYSTEM OPERATIONAL` : 'SYSTEM OFFLINE'}
          </span>
          {health.connected && <span className="text-text-muted">{health.latency} ms</span>}
          {/* WebSocket live indicator */}
          <span
            title={wsConnected ? 'Live updates active' : 'Reconnecting…'}
            className={`ml-2 w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-success animate-pulse' : 'bg-warning'}`}
          />
        </div>

        <div className="flex items-center justify-end gap-6 w-1/3">
          <span className="text-xs font-medium text-text-secondary tracking-wide uppercase">Alice Dispatcher</span>
          <button 
            onClick={() => {
              localStorage.removeItem('token');
              navigate('/login');
            }}
            className="text-xs text-text-muted hover:text-text-primary transition-colors uppercase tracking-wider"
          >
            Logout
          </button>
        </div>
      </header>
      
      {/* MAIN WORKSPACE - CSS Grid */}
      <main className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_320px]">
        {/* MAP CONTAINER */}
        <div className="h-full border-r border-border-subtle relative bg-bg-surface">
          <LiveMap onStatsUpdate={setStats} refreshTick={refreshTick} />
        </div>
        
        {/* REVIEW QUEUE PANEL */}
        <div className="h-full bg-bg-surface overflow-hidden flex flex-col">
          <ReviewQueue refreshTick={refreshTick} />
        </div>
      </main>


      {/* STATUS BAR - 32px fixed */}
      <footer className="h-8 shrink-0 border-t border-border-subtle bg-bg-surface flex items-center justify-between px-4 text-[11px] font-medium text-text-muted uppercase tracking-wider">
        <div className="flex items-center gap-6">
          <span>Last Update {new Date().toLocaleTimeString('en-US', { hour12: false, timeZoneName: 'short' })}</span>
          <div className="flex items-center gap-4 text-text-secondary">
            <span>{stats.needs} Needs Active</span>
            <span>{stats.resources} Resources Available</span>
          </div>
        </div>
        <div>
          <button 
            onClick={() => setShowReportModal(true)}
            className="hover:text-text-primary transition-colors font-semibold tracking-wider flex items-center gap-1"
          >
            + Report
          </button>
        </div>
      </footer>

      {showReportModal && <ReportModal onClose={() => setShowReportModal(false)} />}
    </div>
  );
}