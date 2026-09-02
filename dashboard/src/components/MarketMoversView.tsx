import React, { useState, useEffect } from 'react';
import { fetchMarketMovers, getStoredBackendUrl } from '../services/api';
import { MoverItem } from '../types/datafeed';
import { ApiSpecDrawer } from './ApiSpecDrawer';

export const MarketMoversView: React.FC = () => {
  const [kind, setKind] = useState<string>('top_gainers');
  const [movers, setMovers] = useState<MoverItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  const categories = [
    { id: 'top_gainers', label: 'Top Gainers' },
    { id: 'top_losers', label: 'Top Losers' },
    { id: 'top_volume', label: 'Top Volume' },
    { id: 'top_value', label: 'Top Value' },
    { id: 'top_frequency', label: 'Top Frequency' },
    { id: 'net_foreign_buy', label: 'Net Foreign Buy' },
    { id: 'net_foreign_sell', label: 'Net Foreign Sell' },
    { id: 'iev_top_gainers', label: 'IEP/IEV Indication' },
  ];

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    const loadData = async () => {
      const data = await fetchMarketMovers(kind, getStoredBackendUrl());
      if (mounted) {
        setMovers(data);
        setLoading(false);
      }
    };

    loadData();
    return () => {
      mounted = false;
    };
  }, [kind]);

  return (
    <div className="space-y-4 font-mono text-[13px]">
      <ApiSpecDrawer
        method="GET"
        endpoint="/v1/market/movers"
        queryParams={`?kind=${kind}`}
        useCaseTitle="Market Momentum & Volatility Screening"
        useCaseDescription="Discovers leading momentum leaders, panic sell-offs, liquidity magnets, institutional foreign accumulation, and pre-market indicative equilibrium prices (IEP/IEV) across 800+ IDX tickers."
        curlCommand={`curl -s "http://127.0.0.1:8000/v1/market/movers?kind=${kind}"`}
        responsePreview={`{
  "kind": "${kind}",
  "movers": [
    { "symbol": "BWPT", "last": "132", "change": "23", "change_pct": "21.10%" }
  ]
}`}
      />

      {/* Control Strip */}
      <div className="flex flex-wrap items-center gap-2 p-3 bg-[#000000] border border-[#202020] rounded-[2px]">
        <span className="text-[#7e7e7e] text-[12px]">Category:</span>
        {categories.map((c) => (
          <button
            key={c.id}
            onClick={() => setKind(c.id)}
            className={`btn-action-sm ${kind === c.id ? 'active' : ''}`}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Movers Table */}
      <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
        {loading && movers.length === 0 ? (
          <div className="p-8 text-center text-[#7e7e7e]">Fetching market movers...</div>
        ) : movers.length === 0 ? (
          <div className="p-8 text-center text-[#7e7e7e]">No records found for {kind}.</div>
        ) : (
          <table className="w-full text-left font-mono text-[12px]">
            <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
              <tr>
                <th className="py-2.5 px-3 font-normal">RANK</th>
                <th className="py-2.5 px-3 font-normal">SYMBOL</th>
                <th className="py-2.5 px-3 font-normal">NAME</th>
                <th className="py-2.5 px-3 font-normal text-right">PRICE (RP)</th>
                <th className="py-2.5 px-3 font-normal text-right">CHANGE</th>
                <th className="py-2.5 px-3 font-normal text-right">CHANGE %</th>
                <th className="py-2.5 px-3 font-normal text-right">VOLUME</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
              {movers.map((m, idx) => {
                const pctNum = parseFloat(m.change_pct);
                const isPositive = !isNaN(pctNum) ? pctNum >= 0 : parseFloat(m.change) >= 0;
                const changeStr = parseFloat(m.change) > 0 ? `+${m.change}` : m.change;
                const pctDisplay = !isNaN(pctNum) ? (isPositive ? `+${pctNum.toFixed(2)}%` : `${pctNum.toFixed(2)}%`) : `${m.change_pct}%`;

                return (
                  <tr key={idx} className="hover:bg-[#191919] transition-colors">
                    <td className="py-2 px-3 text-[#7e7e7e]">#{idx + 1}</td>
                    <td className="py-2 px-3 font-bold text-[#eeeeee]">{m.symbol}</td>
                    <td className="py-2 px-3 text-[#b4b4b4] truncate max-w-[200px]">{m.name || '—'}</td>
                    <td className="py-2 px-3 text-right font-bold text-[#eeeeee]">
                      {parseInt(m.last, 10).toLocaleString()}
                    </td>
                    <td className="py-2 px-3 text-right">{changeStr}</td>
                    <td className="py-2 px-3 text-right">
                      <span className={`px-1.5 py-0.5 rounded-[2px] font-bold text-[11px] ${isPositive ? 'text-[#eeeeee] bg-[#202020]' : 'text-[#da5c2c] bg-[#191919] border border-[#da5c2c]'}`}>
                        {pctDisplay}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-right text-[#b4b4b4]">
                      {m.volume ? m.volume.toLocaleString() : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
