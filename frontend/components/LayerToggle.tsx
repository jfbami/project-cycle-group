'use client';

import { TIER_META, ALL_TIERS, type RiskTier, type LayerVisibility } from '@/lib/types';

interface Props {
  layers: LayerVisibility;
  onLayerToggle: (key: keyof LayerVisibility) => void;
  activeTiers: RiskTier[];
  onTierToggle: (tier: RiskTier) => void;
}

const LAYER_LABELS: Record<keyof LayerVisibility, string> = {
  circles:      'Circles',
  bikeFacility: 'Bike Facility Ring',
};

export default function LayerToggle({ layers, onLayerToggle, activeTiers, onTierToggle }: Props) {
  return (
    <div className="bg-gray-900/90 backdrop-blur-sm border border-gray-700 rounded-lg p-3 min-w-[11rem] space-y-3">

      <div>
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-2">Layers</p>
        <div className="flex flex-col gap-2">
          {(Object.keys(layers) as (keyof LayerVisibility)[]).map((key) => (
            <label key={key} className="flex items-center gap-2 cursor-pointer select-none group">
              <input type="checkbox" checked={layers[key]} onChange={() => onLayerToggle(key)}
                className="w-3.5 h-3.5 cursor-pointer accent-cyan-500" />
              <span className="text-sm text-gray-300 group-hover:text-white transition-colors">
                {LAYER_LABELS[key]}
              </span>
            </label>
          ))}
        </div>
      </div>

      <div className="border-t border-gray-700 pt-2">
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-2">Risk Tier</p>
        <div className="flex flex-col gap-1.5">
          {ALL_TIERS.map((tier) => {
            const { label, color } = TIER_META[tier];
            const active = activeTiers.includes(tier);
            return (
              <label key={tier} className="flex items-center gap-2 cursor-pointer select-none group">
                <input type="checkbox" checked={active} onChange={() => onTierToggle(tier)}
                  className="w-3.5 h-3.5 cursor-pointer" style={{ accentColor: color }} />
                <div className="w-2.5 h-2.5 rounded-full flex-shrink-0 transition-opacity"
                  style={{ backgroundColor: color, opacity: active ? 1 : 0.3 }} />
                <span className={`text-sm transition-colors ${active ? 'text-gray-200' : 'text-gray-500'} group-hover:text-white`}>
                  {label}
                </span>
              </label>
            );
          })}
        </div>
      </div>

    </div>
  );
}
