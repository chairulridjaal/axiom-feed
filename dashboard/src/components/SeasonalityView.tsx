import React, { useState, useEffect } from 'react';
import { fetchSeasonality, getStoredBackendUrl } from '../services/api';
import { ApiSpecDrawer } from './ApiSpecDrawer';

interface SeasonalityViewProps {
  selectedSymbol: string;
}

export const SeasonalityView: React.FC<SeasonalityViewProps> = ({ selectedSymbol }) => {
  const [seasonalityData, setSeasonalityData] = useState<any>(null);
  const [backYear, setBackYear] = useState<number>(5);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    const loadData = async () => {
      const data = await fetchSeasonality(selectedSymbol, 2026, backYear, getStoredBackendUrl());
      if (mounted) {
        if (data) setSeasonalityData(data);
        setLoading(false);
      }
    };

    loadData();
    return () => {
      mounted = false;
    };
  }, [selectedSymbol, backYear]);

  const priceChanges = seasonalityData?.price_change || [];

  return (
    <div className="space-y-4 font-mono text-[13px]">
      <ApiSpecDrawer
        method="GET"
        endpoint="/v1/seasonality/:symbol"
        queryParams="?year=2026&back_year=5"
        useCaseTitle="Historical Monthly Return Probability & Seasonality Matrices"
        useCaseDescription="Dissects multi-year cyclical patterns and monthly return distributions. Used by algorithmic strategies to identify high-probability seasonal anomalies (e.g. 'Sell in May', Window Dressing, Santa Claus rally) across IDX tickers."
        curlCommand={`curl -s "http://127.0.0.1:8000/v1/seasonality/${selectedSymbol}?year=2026&back_year=${backYear}"`}
        responsePreview={`{
  "symbol": "${selectedSymbol}",
  "year": 2026,
  "back_year": ${backYear}
}`}
      />

      {/* Controls */}
      <div className="flex items-center justify-between p-3 bg-[#000000] border border-[#202020] rounded-[2px]">
        <div className="flex items-center gap-2">
          <span className="text-[#7e7e7e]">Lookback Period:</span>
          {[3, 5, 10].map((y) => (
            <button
              key={y}
              onClick={() => setBackYear(y)}
              className={`btn-action-sm ${backYear === y ? 'active' : ''}`}
            >
              {y} Years
            </button>
          ))}
        </div>
        <span className="text-[#7e7e7e] text-[11px]">
          Green: Positive Returns · Red: Negative Returns
        </span>
      </div>

      {/* Heatmap Matrix Table */}
      <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-[#7e7e7e]">Loading seasonality matrix for {selectedSymbol}...</div>
        ) : priceChanges.length === 0 ? (
          <div className="p-8 text-center text-[#7e7e7e]">No seasonality data available for {selectedSymbol}.</div>
        ) : (
          <table className="w-full text-left font-mono text-[12px]">
            <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
              <tr>
                <th className="py-2 px-3 font-normal">YEAR</th>
                <th className="py-2 px-3 font-normal text-right">TOTAL</th>
                {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map((m) => (
                  <th key={m} className="py-2 px-2.5 font-normal text-right">{m.toUpperCase()}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#202020]">
              {priceChanges.map((row: any) => {
                const cols: any[] = row.columns || [];
                const yearVal = cols.find((c) => c.name === 'Year')?.value || '—';
                const yearColor = cols.find((c) => c.name === 'Year')?.color;

                return (
                  <tr key={row.row} className="hover:bg-[#191919] transition-colors">
                    <td className="py-2 px-3 font-bold text-[#eeeeee]">{row.row}</td>
                    <td className="py-2 px-3 text-right font-bold" style={{ color: yearColor || '#eeeeee' }}>
                      {yearVal}%
                    </td>
                    {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map((m) => {
                      const col = cols.find((c) => c.name === m);
                      if (!col || col.value === undefined) {
                        return <td key={m} className="py-2 px-2.5 text-right text-[#3a3a3a]">—</td>;
                      }
                      const num = parseFloat(col.value);
                      const isPos = num >= 0;
                      return (
                        <td
                          key={m}
                          className="py-2 px-2.5 text-right font-bold text-[11px]"
                          style={{ color: col.color || (isPos ? '#00A859' : '#E70000') }}
                        >
                          {isPos ? `+${col.value}%` : `${col.value}%`}
                        </td>
                      );
                    })}
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
