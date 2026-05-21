import { TIER_META, ALL_TIERS } from '@/lib/types';

export default function Legend() {
  return (
    <div className="bg-gray-900/90 backdrop-blur-sm border border-gray-700 rounded-lg p-3 space-y-3">
      <div>
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-2">
          Risk Tier
        </p>
        <div className="flex flex-col gap-1.5">
          {ALL_TIERS.map((tier) => {
            const { label, color, range } = TIER_META[tier];
            return (
              <div key={tier} className="flex items-center gap-2">
                <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
                <span className="text-xs text-gray-300">{label}</span>
                <span className="text-[10px] text-gray-500 ml-auto pl-2">{range}</span>
              </div>
            );
          })}
        </div>
      </div>

      <div className="pt-2 border-t border-gray-700">
        <p className="text-[10px] text-gray-500 mb-1.5">Circle size = risk score</p>
        <div className="flex items-end gap-2">
          {[6, 10, 16].map((r) => (
            <div key={r} className="rounded-full bg-gray-500" style={{ width: r, height: r }} />
          ))}
          <span className="text-[10px] text-gray-500 ml-1">higher →</span>
        </div>
      </div>

      <div className="pt-2 border-t border-gray-700">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full border-2 border-cyan-400 flex-shrink-0" />
          <span className="text-xs text-gray-300">Bike facility</span>
        </div>
      </div>
    </div>
  );
}
