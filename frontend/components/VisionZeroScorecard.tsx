import type { ScorecardStats } from '@/lib/types';

interface Props {
  stats: ScorecardStats;
  totalIntersections: number;
}

function Stat({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className="flex flex-col items-center">
      <span className={`text-base font-bold tabular-nums ${highlight ? 'text-red-400' : 'text-white'}`}>
        {value}
      </span>
      <span className="text-[10px] text-gray-400 uppercase tracking-wider">{label}</span>
    </div>
  );
}

export default function VisionZeroScorecard({ stats, totalIntersections }: Props) {
  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 bg-gray-900/92 backdrop-blur-sm border border-gray-700 rounded-lg px-5 py-2.5 flex items-center gap-5 whitespace-nowrap">
      <div className="flex flex-col">
        <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest leading-tight">
          Capitol Hill · 2018–23
        </span>
        <span className="text-xs text-gray-500">{stats.count} / {totalIntersections} intersections</span>
      </div>

      <div className="w-px h-7 bg-gray-700" />

      <div className="flex items-center gap-5">
        <Stat label="Crashes"  value={stats.crashes}  />
        <Stat label="Injuries" value={stats.injuries} />
        <Stat label="KSI"      value={stats.ksi}      highlight={stats.ksi > 0} />
        <Stat label="Fatal"    value={stats.fatal}    highlight={stats.fatal > 0} />
        <Stat label="Ped"      value={stats.ped}      />
        <Stat label="Bike"     value={stats.bike}     />
      </div>
    </div>
  );
}
