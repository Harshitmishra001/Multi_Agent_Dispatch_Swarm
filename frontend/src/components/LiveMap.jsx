import React, { useState, useEffect } from 'react';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import client from '../api/client';
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

// Clean SVG marker for NEEDS (Red circle)
const createNeedIcon = (urgency) => {
  const color = urgency === 'CRITICAL' ? '#ef4444' : urgency === 'HIGH' ? '#f59e0b' : '#a1a1aa';
  return L.divIcon({
    className: 'custom-icon',
    html: `<svg width="12" height="12" viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg">
      <circle cx="6" cy="6" r="4" fill="${color}" stroke="#18181b" stroke-width="1.5" />
      <circle cx="6" cy="6" r="5.5" fill="none" stroke="${color}" stroke-opacity="0.3" stroke-width="1" />
    </svg>`,
    iconSize: [12, 12],
    iconAnchor: [6, 6]
  });
};

// Clean SVG marker for RESOURCES (Blue square)
const resourceIcon = L.divIcon({
  className: 'custom-icon',
  html: `<svg width="12" height="12" viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg">
    <rect x="2" y="2" width="8" height="8" fill="#3b82f6" stroke="#18181b" stroke-width="1.5" />
  </svg>`,
  iconSize: [12, 12],
  iconAnchor: [6, 6]
});

// Component to handle auto-bounding the map
const BoundsFitter = ({ needs, resources }) => {
  const map = useMap();
  useEffect(() => {
    if (needs.length === 0 && resources.length === 0) return;
    const bounds = L.latLngBounds();
    let hasPoints = false;
    needs.forEach(n => { if (n.lat && n.lon) { bounds.extend([n.lat, n.lon]); hasPoints = true; }});
    resources.forEach(r => { if (r.lat && r.lon) { bounds.extend([r.lat, r.lon]); hasPoints = true; }});
    if (hasPoints) {
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 14 });
    }
  }, [needs, resources, map]);
  return null;
};

const LiveMap = ({ onStatsUpdate, refreshTick = 0 }) => {
  const [resources, setResources] = useState([]);
  const [needs, setNeeds] = useState([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [resReq, needsReq] = await Promise.all([
          client.get('/resources'),
          client.get('/needs')
        ]);
        const resData = resReq.data.resources || [];
        const needData = needsReq.data.needs || [];
        setResources(resData);
        setNeeds(needData);
        if (onStatsUpdate) {
          onStatsUpdate({ needs: needData.length, resources: resData.length });
        }
      } catch (err) {
        console.error('Error fetching map data', err);
      }
    };
    
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [onStatsUpdate, refreshTick]);

  // Houston coords as fallback
  const fallbackCenter = [29.7604, -95.3698];

  return (
    <div className="h-full w-full relative">
      <MapContainer 
        center={fallbackCenter} 
        zoom={11} 
        style={{ height: '100%', width: '100%', background: '#18181b' }}
        zoomControl={false}
        attributionControl={false}
      >
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png"
        />
        <TileLayer
          url="https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png"
          zIndex={10}
        />
        <BoundsFitter needs={needs} resources={resources} />
        
        {resources.map(res => {
          if (!res.lat || !res.lon) return null;
          return (
            <Marker key={res.resource_id} position={[res.lat, res.lon]} icon={resourceIcon}>
              <Popup className="custom-popup" closeButton={false}>
                <div className="text-xs p-2 bg-bg-elevated text-text-primary border border-border-subtle rounded-sm">
                  <div className="font-semibold text-accent uppercase tracking-wider mb-1">{res.resource_type} DEPOT</div>
                  <div className="text-text-secondary">ID: {res.resource_id}</div>
                  <div>Qty: {res.quantity_available} units</div>
                </div>
              </Popup>
            </Marker>
          );
        })}

        {needs.map(need => {
          if (!need.lat || !need.lon) return null;
          return (
            <Marker key={need.need_id} position={[need.lat, need.lon]} icon={createNeedIcon(need.urgency)}>
              <Popup className="custom-popup" closeButton={false}>
                <div className="text-xs p-2 bg-bg-elevated text-text-primary border border-border-subtle rounded-sm">
                  <div className={`font-semibold uppercase tracking-wider mb-1 ${
                    need.urgency === 'CRITICAL' ? 'text-critical' : need.urgency === 'HIGH' ? 'text-high' : 'text-text-muted'
                  }`}>
                    {need.urgency} NEED
                  </div>
                  <div className="text-text-secondary mb-1">ID: {need.need_id}</div>
                  <div className="text-text-primary">{need.location_text}</div>
                  <div className="mt-1">Req: {need.quantity_estimate} {need.need_type}</div>
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>

      {/* Global override for Leaflet popup styles to match dark theme */}
      <style>{`
        .leaflet-popup-content-wrapper {
          background: transparent;
          box-shadow: none;
          padding: 0;
          border-radius: 0;
        }
        .leaflet-popup-content {
          margin: 0;
        }
        .leaflet-popup-tip-container {
          display: none;
        }
      `}</style>
    </div>
  );
};

export default LiveMap;