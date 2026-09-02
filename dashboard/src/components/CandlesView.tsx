import React, { useState, useMemo, useEffect } from 'react';
import { fetchLiveCandles, fetchPricePerformance, getStoredBackendUrl } from '../services/api';
import { Candle, HistoricalSlice, Resolution } from '../types/datafeed';
import { ApiSpecDrawer } from './ApiSpecDrawer';

interface CandlesViewProps {
  selectedSymbol: string;
}

export const CandlesView: React.FC<CandlesViewProps> = ({ selectedSymbol }) => {
  const [resolution, setResolution] = useState<Resolution>('daily');
  const [rangeMonths, setRangeMonths] = useState<number>(12);
  const [candles, setCandles] = useState<Candle[]>([]);
  const [performance, setPerformance] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  const { fromDate, toDate, fromStr, toStr } = useMemo(() => {
    const to = new Date();
    const from = new Date();
    from.setMonth(from.getMonth() - rangeMonths);
    return {
      fromDate: from,
      toDate: to,
      fromStr: from.toISOString().split('T')[0],
      toStr: to.toISOString().split('T')[0],
    };
  }, [rangeMonths]);

  const slices: HistoricalSlice[] = useMemo(() => {
    const sliceDays = resolution === 'daily' ? 365 : 90;
    const windowList: HistoricalSlice[] = [];
    let cur = new Date(fromDate);
    let idx = 0;

    while (cur <= toDate) {
      const nxt = new Date(cur);
      nxt.setDate(nxt.getDate() + sliceDays);
      const windowEnd = nxt < toDate ? nxt : new Date(toDate);

      const wFromStr = cur.toISOString().split('T')[0];
      const wToStr = windowEnd.toISOString().split('T')[0];

      windowList.push({
        windowIndex: idx + 1,
        from: wFromStr,
        to: wToStr,
        fromParam: wToStr,
        toParam: wFromStr,
        resolution,
        candleCount: Math.round((windowEnd.getTime() - cur.getTime()) / 86400000 * 0.69),
        cacheStatus: idx === 0 ? 'HIT' : 'MISS',
        sizeBytes: 15000,
      });

      if (windowEnd >= toDate) break;
      cur = new Date(windowEnd);
      cur.setDate(cur.getDate() + 1);
      idx++;
    }

    return windowList;
  }, [fromDate, toDate, resolution]);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    const loadData = async () => {
      const [cData, pData] = await Promise.all([
        fetchLiveCandles(selectedSymbol, fromStr, toStr, resolution, getStoredBackendUrl()),
        fetchPricePerformance(selectedSymbol, getStoredBackendUrl()),
      ]);
      if (mounted) {
        setCandles(cData);
        setPerformance(pData);
        setLoading(false);
      }
    };

    loadData();
    return () => {
      mounted = false;
    };
  }, [selectedSymbol, fromStr, toStr, resolution, rangeMonths]);

  return (
    <div className="space-y-4 font-mono text-[13px]">
      <ApiSpecDrawer
        method="GET"
        endpoint="/v1/candles/:symbol"
        queryParams={`?from=${fromStr}&to=${toStr}&resolution=${resolution} · /v1/charts/${selectedSymbol}/performance`}
        useCaseTitle="Historical Candlestick Slicing & Multi-Horizon Returns"
        useCaseDescription="Streams continuous OHLCV historical bars through concurrent chunked window slicing streamed line-by-line via NDJSON. Paired with multi-timeframe return metrics across 1D to 10Y horizons."
        curlCommand={`curl -s "http://127.0.0.1:8000/v1/candles/${selectedSymbol}?from=${fromStr}&to=${toStr}&resolution=${resolution}" | head`}
        responsePreview={`{"ts":"2026-09-02T00:00:00+07:00","open":"6675","high":"6725","low":"6600","close":"6675","volume":108537400}`}
      />

      {/* Multi-Horizon Price Performance Strip */}
      {performance.length > 0 && (
        <div className="border border-[#202020] bg-[#111111] p-3 rounded-[2px] space-y-2">
          <div className="flex justify-between items-center text-[11px] text-[#7e7e7e] font-bold">
            <span>MULTI-TIMEFRAME PRICE PERFORMANCE ({selectedSymbol})</span>
            <code>GET /v1/charts/{selectedSymbol}/performance</code>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 md:grid-cols-10 gap-2">
            {performance.map((p, idx) => {
              const isPos = !p.percentage?.formatted?.includes('-');
              return (
                <div key={idx} className="p-2 bg-[#000000] border border-[#202020] rounded-[2px] text-center">
                  <div className="text-[#7e7e7e] text-[10px]">{p.timeframe}</div>
                  <div className={`font-bold text-[12px] mt-0.5 ${isPos ? 'text-[#eeeeee]' : 'text-[#da5c2c]'}`}>
                    {p.percentage?.formatted || '—'}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Range & Resolution Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-[#000000] border border-[#202020] rounded-[2px]">
        <div className="flex items-center gap-2">
          <span className="text-[#7e7e7e] text-[12px]">Range:</span>
          {[1, 3, 6, 12, 24, 60].map((m) => (
            <button
              key={m}
              onClick={() => setRangeMonths(m)}
              className={`btn-action-sm ${rangeMonths === m ? 'active' : ''}`}
            >
              {m >= 12 ? `${m / 12}Y` : `${m}M`}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[#7e7e7e] text-[12px]">Resolution:</span>
          <button
            onClick={() => setResolution('daily')}
            className={`btn-action-sm ${resolution === 'daily' ? 'active' : ''}`}
          >
            Daily (365d slice)
          </button>
          <button
            onClick={() => setResolution('minute')}
            className={`btn-action-sm ${resolution === 'minute' ? 'active' : ''}`}
          >
            Minute (90d slice)
          </button>
        </div>
      </div>

      {/* Slices Info */}
      <div className="border border-[#202020] bg-[#111111] rounded-[2px] p-3 text-[12px]">
        <div className="flex justify-between items-center text-[#b4b4b4] pb-2 border-b border-[#202020] mb-2">
          <div>
            <span className="text-[#7e7e7e]">Stream Range: </span>
            <span className="text-[#eeeeee] font-bold">{fromStr} → {toStr}</span>
            <span className="text-[#7e7e7e] ml-2">({slices.length} {slices.length === 1 ? 'slice' : 'slices'})</span>
          </div>
          <span className="text-[#7e7e7e]">{loading ? 'Streaming NDJSON...' : `${candles.length} bars loaded`}</span>
        </div>
      </div>

      {/* Candlestick Table */}
      <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
        {loading && candles.length === 0 ? (
          <div className="p-8 text-center text-[#7e7e7e]">Streaming historical candles...</div>
        ) : candles.length === 0 ? (
          <div className="p-8 text-center text-[#7e7e7e]">No historical candles returned for selected range.</div>
        ) : (
          <table className="w-full text-left font-mono text-[12px]">
            <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
              <tr>
                <th className="py-2.5 px-3 font-normal">TIMESTAMP (WIB)</th>
                <th className="py-2.5 px-3 font-normal text-right">OPEN</th>
                <th className="py-2.5 px-3 font-normal text-right">HIGH</th>
                <th className="py-2.5 px-3 font-normal text-right">LOW</th>
                <th className="py-2.5 px-3 font-normal text-right">CLOSE</th>
                <th className="py-2.5 px-3 font-normal text-right">VOLUME</th>
                <th className="py-2.5 px-3 font-normal text-right">FREQ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
              {candles.map((c, i) => (
                <tr key={i} className="hover:bg-[#191919] transition-colors">
                  <td className="py-2 px-3 text-[#7e7e7e]">
                    {resolution === 'daily' ? c.ts.split('T')[0] : c.ts.replace('+07:00', '').replace('T', ' ')}
                  </td>
                  <td className="py-2 px-3 text-right">{parseFloat(c.open).toLocaleString()}</td>
                  <td className="py-2 px-3 text-right">{parseFloat(c.high).toLocaleString()}</td>
                  <td className="py-2 px-3 text-right">{parseFloat(c.low).toLocaleString()}</td>
                  <td className="py-2 px-3 text-right font-bold text-[#eeeeee]">{parseFloat(c.close).toLocaleString()}</td>
                  <td className="py-2 px-3 text-right text-[#b4b4b4]">{c.volume ? c.volume.toLocaleString() : '—'}</td>
                  <td className="py-2 px-3 text-right text-[#7e7e7e]">{c.freq ? c.freq.toLocaleString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
