import React, { useState } from 'react';
import client from '../api/client';

const ReviewModal = ({ item, onClose, onComplete }) => {
  const [loading, setLoading] = useState(false);

  const handleAction = async (action) => {
    setLoading(true);
    try {
      await client.post(`/needs/${item.need_id}/review`, { action });
      onComplete();
    } catch (err) {
      console.error('Error submitting review action:', err);
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4">
      <div className="bg-bg-surface border border-border-subtle w-full max-w-md rounded-[2px] shadow-2xl overflow-hidden flex flex-col">
        <div className="h-10 border-b border-border-subtle flex items-center justify-between px-4 bg-bg-elevated">
          <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            Review Extraction
          </span>
          <button onClick={onClose} className="text-text-muted hover:text-text-primary">✕</button>
        </div>

        <div className="p-4 flex flex-col gap-4 text-sm">
          <div className="flex justify-between items-center border-b border-border-subtle pb-2">
            <span className="text-text-muted uppercase text-xs">Need ID</span>
            <span className="font-mono text-text-primary text-xs">{item.need_id}</span>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-text-muted uppercase text-xs">Location</span>
            <span className="text-text-primary">{item.location_text}</span>
            {item.lat && item.lon && (
              <span className="text-text-secondary text-xs font-mono">{item.lat.toFixed(4)}, {item.lon.toFixed(4)}</span>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4 border-t border-border-subtle pt-4">
            <div className="flex flex-col gap-1">
              <span className="text-text-muted uppercase text-xs">Category</span>
              <span className="text-text-primary capitalize">{item.need_type}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-text-muted uppercase text-xs">Quantity</span>
              <span className="text-text-primary">{item.quantity_estimate}</span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-text-muted uppercase text-xs">Urgency</span>
              <span className={`uppercase font-semibold text-xs ${
                item.urgency === 'CRITICAL' ? 'text-critical' : 
                item.urgency === 'HIGH' ? 'text-high' : 'text-text-primary'
              }`}>
                {item.urgency}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-text-muted uppercase text-xs">Confidence</span>
              <span className="text-text-primary">{((item.verification_confidence ?? item.extraction_confidence ?? 0) * 100).toFixed(1)}%</span>
            </div>
          </div>
        </div>

        <div className="p-4 border-t border-border-subtle bg-bg-elevated flex gap-3 justify-end">
          <button 
            onClick={() => handleAction('reject')}
            disabled={loading}
            className="text-xs uppercase tracking-wider font-semibold text-critical hover:text-red-400 px-4 py-2 transition-colors disabled:opacity-50"
          >
            Reject
          </button>
          <button 
            onClick={() => handleAction('approve')}
            disabled={loading}
            className="text-xs uppercase tracking-wider font-semibold bg-success hover:bg-green-400 text-black px-6 py-2 rounded-[2px] transition-colors disabled:opacity-50"
          >
            Approve & Dispatch
          </button>
        </div>
      </div>
    </div>
  );
};

export default ReviewModal;
