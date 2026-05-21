'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import ReactMap, {
  Layer, Source, NavigationControl, ScaleControl,
  type MapRef, type MapLayerMouseEvent,
} from 'react-map-gl';
import type { FeatureCollection } from 'geojson';
import { type RiskTier, type SelectedIntersection } from '@/lib/types';
import { fetchBikeFacilities } from '@/lib/api';
import 'mapbox-gl/dist/mapbox-gl.css';

interface Props {
  intersections: FeatureCollection | null;
  activeTiers: RiskTier[];
  onTierToggle: (tier: RiskTier) => void;
  onIntersectionClick: (i: SelectedIntersection | null) => void;
}

// Capitol Hill, Seattle
const INITIAL_VIEW = { longitude: -122.3149, latitude: 47.6188, zoom: 14.5 };

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const TIER_COLOR: any = [
  'match', ['get', 'risk_tier'],
  'very_high', '#ef4444',
  'high',      '#f97316',
  'moderate',  '#eab308',
  'low',       '#84cc16',
  'very_low',  '#22c55e',
  '#6b7280',
];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const CIRCLE_RADIUS: any = [
  'interpolate', ['linear'], ['get', 'risk_score'],
  0, 5, 50, 9, 100, 15,
];

export default function TrafficMap({ intersections, activeTiers, onTierToggle: _onTierToggle, onIntersectionClick }: Props) {
  const mapRef = useRef<MapRef>(null);
  const [cursor, setCursor] = useState<'grab' | 'pointer'>('grab');
  const [bikeLines, setBikeLines] = useState<FeatureCollection | null>(null);

  // Load bike facility lines once
  useEffect(() => {
    fetchBikeFacilities()
      .then(setBikeLines)
      .catch(() => {}); // non-critical — map works without it
  }, []);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tierFilter: any = activeTiers.length < 5
    ? ['in', ['get', 'risk_tier'], ['literal', activeTiers]]
    : ['has', 'risk_tier'];

  const handleClick = useCallback((e: MapLayerMouseEvent) => {
    const feature = e.features?.[0];
    if (!feature || feature.layer?.id !== 'intersection-circles') {
      onIntersectionClick(null);
      return;
    }
    const p = feature.properties ?? {};
    onIntersectionClick({
      intersectionId:   Number(p.intersection_id    ?? 0),
      name:             String(p.name               ?? 'Unknown'),
      riskScore:        Number(p.risk_score          ?? 0),
      riskTier:         String(p.risk_tier           ?? 'very_low') as RiskTier,
      predictedCrashes: Number(p.predicted_crashes   ?? 0),
      ebPredicted:      Number(p.eb_predicted        ?? 0),
      observedCrashes:  Number(p.observed_crashes    ?? 0),
      yearsObserved:    Number(p.years_observed      ?? 6),
      injuryTotal:      Number(p.injury_total        ?? 0),
      ksiTotal:         Number(p.ksi_total           ?? 0),
      fatalTotal:       Number(p.fatal_total         ?? 0),
      pedTotal:         Number(p.ped_total           ?? 0),
      bikeTotal:        Number(p.bike_total          ?? 0),
      isSignalized:     Boolean(p.is_signalized),
      numLegs:          Number(p.num_legs            ?? 4),
      maxSpeedLimit:    Number(p.max_speed_limit     ?? 0),
      bikeFacility:     String(p.bike_facility       ?? 'None'),
      arterialClass:    String(p.arterial_class      ?? ''),
      coordinates:      { lat: e.lngLat.lat, lng: e.lngLat.lng },
    });
  }, [onIntersectionClick]);

  const handleMouseMove = useCallback((e: MapLayerMouseEvent) => {
    setCursor(e.features && e.features.length > 0 ? 'pointer' : 'grab');
  }, []);

  const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
  if (!token) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-red-400 text-sm bg-gray-900 px-4 py-2 rounded border border-red-800">
          Missing <code className="font-mono">NEXT_PUBLIC_MAPBOX_TOKEN</code> in <code className="font-mono">.env.local</code>
        </p>
      </div>
    );
  }

  return (
    <ReactMap
      ref={mapRef}
      mapboxAccessToken={token}
      initialViewState={INITIAL_VIEW}
      style={{ width: '100%', height: '100%' }}
      mapStyle="mapbox://styles/mapbox/dark-v11"
      cursor={cursor}
      interactiveLayerIds={['intersection-circles']}
      onClick={handleClick}
      onMouseMove={handleMouseMove}
    >
      <NavigationControl position="top-right" />
      <ScaleControl position="bottom-right" unit="imperial" />

      {/* ── Bike facility lines (real lane geometry) ─────────────────────── */}
      {bikeLines && (
        <Source id="bike-lines" type="geojson" data={bikeLines}>
          {/* Glow / casing */}
          <Layer
            id="bike-lines-glow"
            type="line"
            paint={{
              'line-color': '#06b6d4',
              'line-width': 4,
              'line-opacity': 0.15,
              'line-blur': 3,
            }}
          />
          {/* Main line */}
          <Layer
            id="bike-lines-main"
            type="line"
            paint={{
              'line-color': '#22d3ee',
              'line-width': 1.5,
              'line-opacity': 0.75,
              'line-dasharray': [2, 1.5],
            }}
          />
        </Source>
      )}

      {/* ── Intersection risk circles ─────────────────────────────────────── */}
      {intersections && (
        <Source id="intersections" type="geojson" data={intersections}>
          {/* Outer glow — simulates radial gradient */}
          <Layer
            id="intersection-glow"
            type="circle"
            filter={tierFilter}
            paint={{
              'circle-color': TIER_COLOR,
              'circle-radius': ['*', CIRCLE_RADIUS, 2.2] as any,
              'circle-opacity': 0.12,
              'circle-blur': 1,
              'circle-stroke-width': 0,
            }}
          />
          {/* Mid glow */}
          <Layer
            id="intersection-mid"
            type="circle"
            filter={tierFilter}
            paint={{
              'circle-color': TIER_COLOR,
              'circle-radius': ['*', CIRCLE_RADIUS, 1.45] as any,
              'circle-opacity': 0.22,
              'circle-blur': 0.6,
              'circle-stroke-width': 0,
            }}
          />
          {/* Core circle */}
          <Layer
            id="intersection-circles"
            type="circle"
            filter={tierFilter}
            paint={{
              'circle-color': TIER_COLOR,
              'circle-radius': CIRCLE_RADIUS,
              'circle-opacity': 0.92,
              'circle-blur': 0.08,
              'circle-stroke-width': 0,
            }}
          />
          {/* Bright centre highlight */}
          <Layer
            id="intersection-highlight"
            type="circle"
            filter={tierFilter}
            paint={{
              'circle-color': '#ffffff',
              'circle-radius': ['*', CIRCLE_RADIUS, 0.32] as any,
              'circle-opacity': 0.18,
              'circle-blur': 0.4,
              'circle-stroke-width': 0,
            }}
          />
        </Source>
      )}
    </ReactMap>
  );
}
