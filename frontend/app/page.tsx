'use client';

import { useState, useEffect, useMemo } from 'react';
import dynamic from 'next/dynamic';
import type { FeatureCollection } from 'geojson';
import DrillInPanel from '@/components/DrillInPanel';
import LeftPanel from '@/components/LeftPanel';
import { fetchIntersections } from '@/lib/api';
import { ALL_TIERS, type RiskTier, type SelectedIntersection, type ScorecardStats } from '@/lib/types';

const TrafficMap = dynamic(() => import('@/components/Map'), { ssr: false });

export default function HomePage() {
  const [intersections, setIntersections] = useState<FeatureCollection | null>(null);
  const [selected, setSelected] = useState<SelectedIntersection | null>(null);
  const [activeTiers, setActiveTiers] = useState<RiskTier[]>([...ALL_TIERS]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchIntersections()
      .then(setIntersections)
      .catch(() => setError('Cannot reach the API server.'))
      .finally(() => setLoading(false));
  }, []);

  const toggleTier = (tier: RiskTier) =>
    setActiveTiers(prev =>
      prev.includes(tier) ? prev.filter(t => t !== tier) : [...prev, tier]
    );

  const scorecard = useMemo<ScorecardStats | null>(() => {
    if (!intersections) return null;
    const features = intersections.features.filter(f =>
      activeTiers.includes(f.properties?.risk_tier as RiskTier)
    );
    const sum = (key: string) => features.reduce((acc, f) => acc + (Number(f.properties?.[key]) || 0), 0);
    return {
      count:    features.length,
      crashes:  sum('observed_crashes'),
      injuries: sum('injury_total'),
      ksi:      sum('ksi_total'),
      fatal:    sum('fatal_total'),
      ped:      sum('ped_total'),
      bike:     sum('bike_total'),
    };
  }, [intersections, activeTiers]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950">
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-cyan-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-gray-400 text-sm">Loading intersection data…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950">
        <div className="bg-gray-900 border border-gray-700 rounded-xl p-8 max-w-md w-full mx-4">
          <p className="text-red-400 font-semibold mb-1">Backend not connected</p>
          <p className="text-gray-400 text-sm mb-4">{error}</p>
          <p className="text-gray-500 text-xs mb-2">Start the API server from your Python project:</p>
          <pre className="bg-gray-950 text-cyan-300 text-xs rounded-lg p-3 overflow-x-auto">
            python -m uvicorn api_server:app --port 8000 --reload
          </pre>
          <p className="text-gray-600 text-xs mt-4">
            Then set <code className="text-gray-400">NEXT_PUBLIC_API_URL=http://localhost:8000</code> in <code className="text-gray-400">.env.local</code> and refresh.
          </p>
        </div>
      </div>
    );
  }

  return (
    <main className="flex w-full h-screen overflow-hidden">
      <LeftPanel
        stats={scorecard}
        totalIntersections={intersections?.features.length ?? 0}
        activeTiers={activeTiers}
        onTierToggle={toggleTier}
      />

      <div className="relative flex-1">
        <TrafficMap
          intersections={intersections}
          activeTiers={activeTiers}
          onTierToggle={toggleTier}
          onIntersectionClick={setSelected}
        />
        <DrillInPanel intersection={selected} onClose={() => setSelected(null)} />
      </div>
    </main>
  );
}
