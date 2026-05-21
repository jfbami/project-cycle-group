'use client';

import { TIER_META, ALL_TIERS, type RiskTier, type ScorecardStats } from '@/lib/types';

interface Props {
  stats: ScorecardStats | null;
  totalIntersections: number;
  activeTiers: RiskTier[];
  onTierToggle: (tier: RiskTier) => void;
}

function StatRow({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-gray-400">{label}</span>
      <span className={`text-sm font-semibold tabular-nums ${warn && value > 0 ? 'text-red-400' : 'text-white'}`}>
        {value}
      </span>
    </div>
  );
}

export default function LeftPanel({ stats, totalIntersections, activeTiers, onTierToggle }: Props) {
  return (
    <aside className="w-52 flex-shrink-0 flex flex-col overflow-y-auto z-10"
      style={{ backgroundColor: '#0d0e14', borderRight: '1px solid #1e1f2a' }}>

      {/* Header */}
      <div className="px-4 py-3" style={{ borderBottom: '1px solid #1e1f2a' }}>
        <p className="text-[10px] font-semibold uppercase tracking-widest leading-tight" style={{ color: '#4b4f63' }}>
          Capitol Hill · Seattle
        </p>
        <p className="text-xs font-medium mt-0.5 text-white">Vision Zero Risk Map</p>
        <p className="text-[10px] mt-0.5" style={{ color: '#383b4d' }}>2018 – 2023</p>
      </div>

      {/* Scorecard */}
      {stats && (
        <div className="px-4 py-3 space-y-2" style={{ borderBottom: '1px solid #1e1f2a' }}>
          <p className="text-[10px] font-semibold uppercase tracking-widest" style={{ color: '#4b4f63' }}>
            {stats.count} / {totalIntersections} intersections
          </p>
          <StatRow label="Crashes"  value={stats.crashes}  />
          <StatRow label="Injuries" value={stats.injuries} />
          <StatRow label="KSI"      value={stats.ksi}      warn />
          <StatRow label="Fatal"    value={stats.fatal}    warn />
          <StatRow label="Ped"      value={stats.ped}      />
          <StatRow label="Bike"     value={stats.bike}     />
        </div>
      )}

      {/* Risk Tier Filter */}
      <div className="px-4 py-3" style={{ borderBottom: '1px solid #1e1f2a' }}>
        <p className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: '#4b4f63' }}>Risk Tier</p>
        <div className="flex flex-col gap-1.5">
          {ALL_TIERS.map((tier) => {
            const { label, color, range } = TIER_META[tier];
            const active = activeTiers.includes(tier);
            return (
              <label key={tier} className="flex items-center gap-2 cursor-pointer select-none group">
                <input
                  type="checkbox"
                  checked={active}
                  onChange={() => onTierToggle(tier)}
                  className="w-3.5 h-3.5 cursor-pointer flex-shrink-0"
                  style={{ accentColor: color }}
                />
                <div
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0 transition-opacity"
                  style={{ backgroundColor: color, opacity: active ? 1 : 0.2 }}
                />
                <div className="min-w-0">
                  <p className={`text-xs leading-tight transition-colors group-hover:text-white ${active ? 'text-gray-300' : 'text-gray-600'}`}>
                    {label}
                  </p>
                  <p className="text-[9px]" style={{ color: '#383b4d' }}>{range}</p>
                </div>
              </label>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="px-4 py-3">
        <p className="text-[10px] font-semibold uppercase tracking-widest mb-2" style={{ color: '#4b4f63' }}>Legend</p>
        <p className="text-[10px] mb-1.5" style={{ color: '#383b4d' }}>Circle size = risk score</p>
        <div className="flex items-end gap-2 mb-3">
          {[8, 12, 18].map((r) => (
            <div key={r} className="rounded-full flex-shrink-0" style={{ width: r, height: r, backgroundColor: '#2e3040' }} />
          ))}
          <span className="text-[10px] ml-1" style={{ color: '#383b4d' }}>higher →</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-0.5 flex-shrink-0" style={{ backgroundColor: '#22d3ee' }} />
          <span className="text-[10px]" style={{ color: '#4b4f63' }}>Bike lane</span>
        </div>
      </div>

    </aside>
  );
}
