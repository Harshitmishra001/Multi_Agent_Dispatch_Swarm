import React, { useState, useEffect } from 'react';
import client from '../api/client';
import ReviewModal from './ReviewModal';

const ReviewQueue = ({ refreshTick = 0 }) => {
  const [queue, setQueue] = useState([]);
  const [selectedNeed, setSelectedNeed] = useState(null);

  const fetchQueue = async () => {
    try {
      const response = await client.get('/needs/pending-review');
      setQueue(response.data.queue || []);
    } catch (err) {
      console.error('Error fetching review queue:', err);
    }
  };

  useEffect(() => {
    fetchQueue();
    const interval = setInterval(fetchQueue, 10000);
    return () => clearInterval(interval);
  }, [refreshTick]);

  const handleActionComplete = () => {
    setSelectedNeed(null);
    fetchQueue();
  };

  return (
    <div className="flex flex-col h-full bg-bg-surface border-l border-border-subtle">
      <div className="h-10 shrink-0 border-b border-border-subtle flex items-center justify-between px-4">
        <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
          Review Queue
        </span>
        <span className="text-xs font-mono text-text-muted">
          {queue.length.toString().padStart(2, '0')}
        </span>
      </div>
      
      <div className="flex-1 overflow-y-auto">
        {queue.length === 0 ? (
          <div className="text-xs text-text-muted text-center py-8">
            Queue empty
          </div>
        ) : (
          <div className="flex flex-col">
            {queue.map(item => (
              <div key={item.need_id} className="border-b border-border-subtle p-3 hover:bg-bg-elevated transition-colors">
                <div className="flex justify-between items-start mb-1.5">
                  <span className={`text-[10px] font-bold uppercase tracking-wider ${
                    item.urgency === 'CRITICAL' ? 'text-critical' : 
                    item.urgency === 'HIGH' ? 'text-high' : 'text-text-muted'
                  }`}>
                    {item.urgency || 'UNKNOWN'}
                  </span>
                  <span className="text-[10px] font-mono text-text-muted">{item.need_id}</span>
                </div>
                
                <div className="text-xs text-text-primary mb-1 truncate">
                  {item.location_text}
                </div>
                <div className="text-xs text-text-secondary mb-2 truncate">
                  {item.quantity_estimate} units
                </div>
                
                <div className="flex justify-between items-center mt-2">
                  <div className="flex gap-2 text-[10px] uppercase tracking-wider text-text-muted">
                    <span>{item.need_type}</span>
                    <span>·</span>
                    <span>{((item.verification_confidence ?? item.extraction_confidence ?? 0) * 100).toFixed(0)}% Conf</span>
                  </div>
                  <button 
                    onClick={() => setSelectedNeed(item)}
                    className="text-[10px] font-semibold border border-border-subtle text-text-primary px-3 py-1 rounded-[2px] hover:bg-border-subtle hover:text-white transition-colors uppercase tracking-wider"
                  >
                    Review
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {selectedNeed && (
        <ReviewModal 
          item={selectedNeed} 
          onClose={() => setSelectedNeed(null)} 
          onComplete={handleActionComplete} 
        />
      )}
    </div>
  );
};

export default ReviewQueue;
