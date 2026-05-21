'use client';

import { useEffect } from 'react';
import { TIER_META, type SelectedIntersection } from '@/lib/types';

interface Props {
  intersection: SelectedIntersection | null;
  onClose: () => void;
}

function SeverityBar({ score, tier }: { score: number; tier: SelectedIntersection['riskTier'] }) {
  const { color, label } = TIER_META[tier];
  return (
    <div>
      <div className="flex justify-between text-xs mb-1.5">
        <span className="text-gray-400">Risk Score (percentile)</span>
        <span style={{ color }}>{label} · {score.toFixed(1)}</span>
      </div>
      <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500"
          style={{ width: `${score}%`, backgroundColor: color }} />
      </div>
    </div>
  );
}

function StatCard({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className="bg-gray-800 rounded-lg p-3">
      <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-0.5">{label}</p>
      <p className={`text-base font-semibold tabular-nums leading-tight ${warn ? 'text-red-400' : 'text-white'}`}>
        {value}
      </p>
      {sub && <p className="text-[10px] text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function Badge({ label, active }: { label: string; active: boolean }) {
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium border ${
      active ? 'bg-cyan-900/60 text-cyan-300 border-cyan-700' : 'bg-gray-800 text-gray-500 border-gray-700'
    }`}>
      {label}
    </span>
  );
}

function bikeFacilityLabel(f: string) {
  const lower = f.toLowerCase();
  if (lower.includes('protected')) return '🟢 Protected bike lane';
  if (lower.includes('bike lane') || lower.includes('bike_lane')) return '🟡 Bike lane';
  if (lower.includes('shared'))    return '🔵 Shared lane';
  return '⚫ No bike facility';
}

export default function DrillInPanel({ intersection, onClose }: Props) {
  useEffect(() => {
    if (!intersection) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [intersection, onClose]);

  const i = intersection;

  return (
    <aside
      className={[
        'absolute top-0 right-0 h-full w-80 flex flex-col z-10',
        'transition-transform duration-300 ease-in-out',
        i ? 'translate-x-0' : 'translate-x-full',
      ].join(' ')}
      style={{ backgroundColor: '#0d0e14', borderLeft: '1px solid #1e1f2a' }}
      aria-hidden={!i}>

      <div className="flex items-center justify-between px-4 py-3 flex-shrink-0" style={{ borderBottom: '1px solid #1e1f2a' }}>
        <div className="min-w-0 pr-2">
          <p className="text-[10px] text-gray-500 uppercase tracking-wider">
            ID {i?.intersectionId}
          </p>
          <h2 className="font-semibold text-white text-sm truncate">{i?.name ?? ''}</h2>
        </div>
        <button onClick={onClose} aria-label="Close"
          className="text-gray-400 hover:text-white flex-shrink-0 w-7 h-7 flex items-center justify-center rounded hover:bg-gray-700 text-lg">
          ×
        </button>
      </div>

      {i && (
        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-5">

          <SeverityBar score={i.riskScore} tier={i.riskTier} />

          {/* Model predictions */}
          <div>
            <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-2">
              Crash Prediction (NB + EB)
            </p>
            <div className="grid grid-cols-3 gap-2">
              <StatCard label="NB Predicted"  value={i.predictedCrashes.toFixed(1)} sub="per 6 yr" />
              <StatCard label="EB Adjusted"   value={i.ebPredicted.toFixed(1)}      sub="shrunk" />
              <StatCard label="Observed"       value={String(i.observedCrashes)}     sub={`${i.yearsObserved} yr`} />
            </div>
            <p className="text-[10px] text-gray-600 mt-1.5">
              EB = w·predicted + (1−w)·observed where w = 1/(1+α·predicted)
            </p>
          </div>

          {/* Vision Zero severity */}
          <div>
            <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-2">
              Vision Zero Severity
            </p>
            <div className="grid grid-cols-3 gap-2">
              <StatCard label="Injuries" value={String(i.injuryTotal)} />
              <StatCard label="KSI"      value={String(i.ksiTotal)}   warn={i.ksiTotal > 0} sub="Killed / Serious" />
              <StatCard label="Fatal"    value={String(i.fatalTotal)} warn={i.fatalTotal > 0} />
              <StatCard label="Ped"      value={String(i.pedTotal)}   sub="involved" />
              <StatCard label="Bike"     value={String(i.bikeTotal)}  sub="involved" />
            </div>
          </div>

          {/* Infrastructure */}
          <div>
            <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-2">
              Infrastructure
            </p>
            <div className="grid grid-cols-2 gap-2 mb-2">
              <StatCard label="Speed Limit" value={i.maxSpeedLimit ? `${i.maxSpeedLimit} mph` : 'N/A'} />
              <StatCard label="Legs"        value={String(i.numLegs)} sub="approaches" />
            </div>
            <div className="flex flex-wrap gap-1.5 mb-2">
              <Badge label="Signalized"    active={i.isSignalized} />
              <Badge label={i.arterialClass} active />
            </div>
            <p className="text-sm text-gray-200">{bikeFacilityLabel(i.bikeFacility)}</p>
          </div>

          <div>
            <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Coordinates</p>
            <p className="text-xs text-gray-500 font-mono">
              {i.coordinates.lat.toFixed(5)}, {i.coordinates.lng.toFixed(5)}
            </p>
          </div>

        </div>
      )}
    </aside>
  );
}
