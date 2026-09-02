import React, { useState, useEffect } from 'react';
import { fetchBrokersTop, fetchBrokerSummary, fetchBrokerTopStocks, fetchBrokerActivity, getStoredBackendUrl } from '../services/api';
import { BrokerItem, BrokerSummary } from '../types/datafeed';
import { ApiSpecDrawer } from './ApiSpecDrawer';

interface BrokersViewProps {
  selectedSymbol: string;
}

export const BrokersView: React.FC<BrokersViewProps> = ({ selectedSymbol }) => {
  const [brokers, setBrokers] = useState<BrokerItem[]>([]);
  const [summary, setSummary] = useState<BrokerSummary | null>(null);
  const [topStocks, setTopStocks] = useState<{ top_buy: any[]; top_sell: any[] }>({ top_buy: [], top_sell: [] });
  const [selectedBroker, setSelectedBroker] = useState<string>('CC');
  const [brokerActivity, setBrokerActivity] = useState<any | null>(null);
  const [activeSubTab, setActiveSubTab] = useState<'bandar' | 'rankings' | 'top_stocks' | 'activity'>('bandar');
  const [filterType, setFilterType] = useState<'ALL' | 'D' | 'F'>('ALL');
  const [stockDirection, setStockDirection] = useState<'BUY' | 'SELL'>('BUY');
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    const loadData = async () => {
      const [topData, sumData, stockData, actData] = await Promise.all([
        fetchBrokersTop(getStoredBackendUrl()),
        fetchBrokerSummary(selectedSymbol, getStoredBackendUrl()),
        fetchBrokerTopStocks(getStoredBackendUrl()),
        fetchBrokerActivity(selectedBroker, getStoredBackendUrl()),
      ]);
      if (mounted) {
        if (topData) setBrokers(topData);
        if (sumData) setSummary(sumData);
        if (stockData) setTopStocks(stockData);
        if (actData) setBrokerActivity(actData);
        setLoading(false);
      }
    };

    loadData();
    return () => {
      mounted = false;
    };
  }, [selectedSymbol, selectedBroker]);

  const filtered = brokers.filter((b) => filterType === 'ALL' || b.type === filterType);
  const maxNet = Math.max(...brokers.map((b) => Math.abs(b.net_val)), 1);

  return (
    <div className="space-y-4 font-mono text-[13px]">
      <ApiSpecDrawer
        method="GET"
        endpoint="/v1/brokers/summary/:symbol"
        queryParams={`/v1/brokers/top · /v1/brokers/top-stocks · /v1/brokers/${selectedBroker}/activity`}
        useCaseTitle="Institutional Flow & Smart Money Tracking (Bandarmology)"
        useCaseDescription="Quantifies foreign institutional (F) vs domestic retail (D) accumulation and distribution across IDX brokers. Used in 'Bandarmology' algorithms to detect institutional buying pressure, block orders, and stealth inventory distribution."
        curlCommand={`curl -s "http://127.0.0.1:8000/v1/brokers/summary/${selectedSymbol}"`}
        responsePreview={`{
  "symbol": "${selectedSymbol}",
  "status": "Big Acc",
  "top_buyers": [ { "code": "XL", "val": 48291000000 } ]
}`}
      />

      {/* Sub-Tab Navigation */}
      <div className="flex flex-wrap items-center gap-2 p-3 bg-[#000000] border border-[#202020] rounded-[2px]">
        <button
          onClick={() => setActiveSubTab('bandar')}
          className={`btn-action-sm ${activeSubTab === 'bandar' ? 'active' : ''}`}
        >
          Bandar Detector ({selectedSymbol})
        </button>
        <button
          onClick={() => setActiveSubTab('rankings')}
          className={`btn-action-sm ${activeSubTab === 'rankings' ? 'active' : ''}`}
        >
          Top Broker Volume Rankings
        </button>
        <button
          onClick={() => setActiveSubTab('top_stocks')}
          className={`btn-action-sm ${activeSubTab === 'top_stocks' ? 'active' : ''}`}
        >
          Top Accumulated Stocks
        </button>
        <button
          onClick={() => setActiveSubTab('activity')}
          className={`btn-action-sm ${activeSubTab === 'activity' ? 'active' : ''}`}
        >
          Broker Activity Log ({selectedBroker})
        </button>
      </div>

      {loading && !summary ? (
        <div className="p-8 text-center text-[#7e7e7e]">Loading institutional flow data...</div>
      ) : (
        <>
          {activeSubTab === 'bandar' && summary && (
            <div className="border border-[#202020] bg-[#111111] p-4 rounded-[2px] space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2.5 border-b border-[#202020]">
                <div className="flex items-center gap-2">
                  <span className="text-[#eeeeee] font-bold text-[14px]">
                    BANDAR ACCUMULATION: {selectedSymbol}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded-[2px] font-bold text-[11px] ${
                      summary.status.includes('Acc')
                        ? 'bg-[#202020] text-[#eeeeee] border border-[#3a3a3a]'
                        : summary.status.includes('Dist')
                        ? 'bg-[#191919] text-[#da5c2c] border border-[#da5c2c]'
                        : 'bg-[#191919] text-[#b4b4b4]'
                    }`}
                  >
                    {summary.status.toUpperCase()}
                  </span>
                  {summary.broker_accdist && (
                    <span className="text-[#7e7e7e] text-[11px]">({summary.broker_accdist})</span>
                  )}
                </div>
                <div className="text-[#7e7e7e] text-[12px]">
                  Average Accumulation Price: <strong className="text-[#eeeeee]">Rp {summary.avg_price.toFixed(1)}</strong>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-[12px]">
                {/* Top Buyers */}
                <div className="space-y-1.5">
                  <div className="text-[#7e7e7e] text-[11px] font-bold">BUYERS (NET ACCUMULATION)</div>
                  {summary.top_buyers.length === 0 ? (
                    <div className="text-[#7e7e7e]">No buyer records</div>
                  ) : (
                    summary.top_buyers.map((b, i) => (
                      <div key={i} className="flex justify-between py-1 border-b border-[#191919]">
                        <div>
                          <span className="text-[#eeeeee] font-bold">{b.broker_code}</span>
                          {b.type && <span className="text-[#7e7e7e] text-[10px] ml-1.5">({b.type})</span>}
                          <div className="text-[#7e7e7e] text-[10px]">Avg: Rp {b.avg_price ? b.avg_price.toFixed(0) : '—'}</div>
                        </div>
                        <div className="text-right">
                          <span className="text-[#eeeeee] font-bold">
                            Rp {(b.value / 1e9).toFixed(2)}B
                          </span>
                          <div className="text-[#7e7e7e] text-[10px]">{b.lots.toLocaleString()} lots</div>
                        </div>
                      </div>
                    ))
                  )}
                </div>

                {/* Top Sellers */}
                <div className="space-y-1.5">
                  <div className="text-[#7e7e7e] text-[11px] font-bold">SELLERS (NET DISTRIBUTION)</div>
                  {summary.top_sellers.length === 0 ? (
                    <div className="text-[#7e7e7e]">No seller records</div>
                  ) : (
                    summary.top_sellers.map((s, i) => (
                      <div key={i} className="flex justify-between py-1 border-b border-[#191919]">
                        <div>
                          <span className="text-[#da5c2c] font-bold">{s.broker_code}</span>
                          {s.type && <span className="text-[#7e7e7e] text-[10px] ml-1.5">({s.type})</span>}
                          <div className="text-[#7e7e7e] text-[10px]">Avg: Rp {s.avg_price ? s.avg_price.toFixed(0) : '—'}</div>
                        </div>
                        <div className="text-right">
                          <span className="text-[#da5c2c] font-bold">
                            Rp {(s.value / 1e9).toFixed(2)}B
                          </span>
                          <div className="text-[#7e7e7e] text-[10px]">{s.lots.toLocaleString()} lots</div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>
          )}

          {activeSubTab === 'rankings' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 bg-[#000000] border border-[#202020] rounded-[2px]">
                <div className="flex items-center gap-2">
                  <span className="text-[#7e7e7e] text-[12px]">Broker Type:</span>
                  <button onClick={() => setFilterType('ALL')} className={`btn-action-sm ${filterType === 'ALL' ? 'active' : ''}`}>All</button>
                  <button onClick={() => setFilterType('F')} className={`btn-action-sm ${filterType === 'F' ? 'active' : ''}`}>Foreign (F)</button>
                  <button onClick={() => setFilterType('D')} className={`btn-action-sm ${filterType === 'D' ? 'active' : ''}`}>Domestic (D)</button>
                </div>
                <span className="text-[#7e7e7e] text-[11px] hidden sm:inline">Blue: Net Inflow · Ember: Net Outflow</span>
              </div>

              <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
                <table className="w-full text-left font-mono text-[12px]">
                  <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
                    <tr>
                      <th className="py-2.5 px-3 font-normal">CODE</th>
                      <th className="py-2.5 px-3 font-normal">BROKER NAME</th>
                      <th className="py-2.5 px-3 font-normal">TYPE</th>
                      <th className="py-2.5 px-3 font-normal text-right">BUY (RP)</th>
                      <th className="py-2.5 px-3 font-normal text-right">SELL (RP)</th>
                      <th className="py-2.5 px-3 font-normal text-right">NET VALUE (RP)</th>
                      <th className="py-2.5 px-3 font-normal text-right">VOLUME</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
                    {filtered.map((b, idx) => {
                      const isNetBuy = b.net_val >= 0;
                      const barWidth = Math.min((Math.abs(b.net_val) / maxNet) * 100, 100);
                      return (
                        <tr key={idx} className="hover:bg-[#191919] transition-colors relative">
                          <td className="py-2 px-3 font-bold text-[#eeeeee]">{b.code}</td>
                          <td className="py-2 px-3 text-[#b4b4b4]">{b.name}</td>
                          <td className="py-2 px-3">
                            <span className={`px-1.5 py-0.5 rounded-[2px] text-[10px] font-bold ${b.type === 'F' ? 'bg-[#202020] text-[#eeeeee]' : 'bg-[#111111] text-[#7e7e7e]'}`}>
                              {b.type === 'F' ? 'FOREIGN' : 'DOMESTIC'}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-right text-[#b4b4b4]">{b.buy_val >= 1e12 ? `${(b.buy_val / 1e12).toFixed(2)}T` : `${(b.buy_val / 1e9).toFixed(1)}B`}</td>
                          <td className="py-2 px-3 text-right text-[#b4b4b4]">{b.sell_val >= 1e12 ? `${(b.sell_val / 1e12).toFixed(2)}T` : `${(b.sell_val / 1e9).toFixed(1)}B`}</td>
                          <td className="py-2 px-3 text-right font-bold relative">
                            <div className={`absolute right-0 top-0 bottom-0 opacity-15 pointer-events-none ${isNetBuy ? 'bg-[#2a7fff]' : 'bg-[#da5c2c]'}`} style={{ width: `${barWidth}%` }} />
                            <span className={`relative z-10 ${isNetBuy ? 'text-[#eeeeee]' : 'text-[#da5c2c]'}`}>
                              {isNetBuy ? `+${(b.net_val / 1e9).toFixed(1)}B` : `${(b.net_val / 1e9).toFixed(1)}B`}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-right text-[#7e7e7e]">{b.buy_vol ? b.buy_vol.toLocaleString() : '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {activeSubTab === 'top_stocks' && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 p-3 bg-[#000000] border border-[#202020] rounded-[2px]">
                <span className="text-[#7e7e7e] text-[12px]">Flow Direction:</span>
                <button
                  onClick={() => setStockDirection('BUY')}
                  className={`btn-action-sm ${stockDirection === 'BUY' ? 'active' : ''}`}
                >
                  Top Accumulated (Buy)
                </button>
                <button
                  onClick={() => setStockDirection('SELL')}
                  className={`btn-action-sm ${stockDirection === 'SELL' ? 'active' : ''}`}
                >
                  Top Distributed (Sell)
                </button>
              </div>

              <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
                <table className="w-full text-left font-mono text-[12px]">
                  <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
                    <tr>
                      <th className="py-2.5 px-3 font-normal">RANK</th>
                      <th className="py-2.5 px-3 font-normal">SYMBOL</th>
                      <th className="py-2.5 px-3 font-normal text-right">NET VALUE</th>
                      <th className="py-2.5 px-3 font-normal text-right">LOTS</th>
                      <th className="py-2.5 px-3 font-normal text-right">AVG PRICE</th>
                      <th className="py-2.5 px-3 font-normal text-right">FOREIGN VALUE</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
                    {(stockDirection === 'BUY' ? topStocks.top_buy : topStocks.top_sell).map((stk: any, idx: number) => {
                      const isBuy = stockDirection === 'BUY';
                      return (
                        <tr key={idx} className="hover:bg-[#191919] transition-colors">
                          <td className="py-2 px-3 text-[#7e7e7e]">#{stk.rank || idx + 1}</td>
                          <td className="py-2 px-3 font-bold text-[#eeeeee]">{stk.code}</td>
                          <td className={`py-2 px-3 text-right font-bold ${isBuy ? 'text-[#eeeeee]' : 'text-[#da5c2c]'}`}>
                            {stk.value?.formatted || (stk.value?.raw ? (parseFloat(stk.value.raw) / 1e9).toFixed(1) + 'B' : '—')}
                          </td>
                          <td className="py-2 px-3 text-right text-[#b4b4b4]">{stk.lot?.formatted || stk.lot?.raw || '—'}</td>
                          <td className="py-2 px-3 text-right text-[#b4b4b4]">Rp {stk.average?.formatted || stk.average?.raw || '—'}</td>
                          <td className="py-2 px-3 text-right text-[#7e7e7e]">{stk.foreign_value?.formatted || '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {activeSubTab === 'activity' && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 p-3 bg-[#000000] border border-[#202020] rounded-[2px]">
                <span className="text-[#7e7e7e] text-[12px]">Broker Code:</span>
                {['CC', 'AK', 'YP', 'XL', 'ZP', 'BK', 'PD', 'KZ'].map((code) => (
                  <button
                    key={code}
                    onClick={() => setSelectedBroker(code)}
                    className={`btn-action-sm ${selectedBroker === code ? 'active' : ''}`}
                  >
                    {code}
                  </button>
                ))}
              </div>

              {brokerActivity && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {/* Buy Log */}
                  <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
                    <div className="bg-[#191919] border-b border-[#202020] p-2.5 text-[#b4b4b4] text-[12px] font-bold">
                      {selectedBroker} BOUGHT STOCKS
                    </div>
                    <div className="divide-y divide-[#202020] max-h-96 overflow-y-auto">
                      {brokerActivity.buys.length === 0 ? (
                        <div className="p-4 text-center text-[#7e7e7e] text-[12px]">No buys recorded</div>
                      ) : (
                        brokerActivity.buys.map((b: any, idx: number) => (
                          <div key={idx} className="p-2.5 flex justify-between items-center hover:bg-[#191919] text-[12px]">
                            <div>
                              <div className="font-bold text-[#eeeeee]">{b.stock}</div>
                              <div className="text-[#7e7e7e] text-[11px]">Avg: Rp {b.avg_price ? b.avg_price.toFixed(0) : '—'}</div>
                            </div>
                            <div className="text-right">
                              <div className="font-bold text-[#eeeeee]">Rp {(b.value / 1e9).toFixed(2)}B</div>
                              <div className="text-[#7e7e7e] text-[11px]">{b.lots.toLocaleString()} lots</div>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  {/* Sell Log */}
                  <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
                    <div className="bg-[#191919] border-b border-[#202020] p-2.5 text-[#b4b4b4] text-[12px] font-bold">
                      {selectedBroker} SOLD STOCKS
                    </div>
                    <div className="divide-y divide-[#202020] max-h-96 overflow-y-auto">
                      {brokerActivity.sells.length === 0 ? (
                        <div className="p-4 text-center text-[#7e7e7e] text-[12px]">No sells recorded</div>
                      ) : (
                        brokerActivity.sells.map((s: any, idx: number) => (
                          <div key={idx} className="p-2.5 flex justify-between items-center hover:bg-[#191919] text-[12px]">
                            <div>
                              <div className="font-bold text-[#da5c2c]">{s.stock}</div>
                              <div className="text-[#7e7e7e] text-[11px]">Avg: Rp {s.avg_price ? s.avg_price.toFixed(0) : '—'}</div>
                            </div>
                            <div className="text-right">
                              <div className="font-bold text-[#da5c2c]">Rp {(s.value / 1e9).toFixed(2)}B</div>
                              <div className="text-[#7e7e7e] text-[11px]">{s.lots.toLocaleString()} lots</div>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};
