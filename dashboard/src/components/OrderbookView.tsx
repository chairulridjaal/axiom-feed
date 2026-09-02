import React, { useState, useEffect } from 'react';
import { fetchLiveBook, fetchLiveQuote, getStoredBackendUrl } from '../services/api';
import { Book, Quote } from '../types/datafeed';
import { ApiSpecDrawer } from './ApiSpecDrawer';

interface OrderbookViewProps {
  selectedSymbol: string;
}

export const OrderbookView: React.FC<OrderbookViewProps> = ({ selectedSymbol }) => {
  const [format, setFormat] = useState<'proto' | 'pipe'>('proto');
  const [book, setBook] = useState<Book | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    const loadData = async () => {
      const [b, q] = await Promise.all([
        fetchLiveBook(selectedSymbol, getStoredBackendUrl()),
        fetchLiveQuote(selectedSymbol, getStoredBackendUrl()),
      ]);
      if (mounted) {
        if (b) setBook(b);
        if (q) setQuote(q);
        setLoading(false);
      }
    };

    loadData();
    const interval = setInterval(loadData, 3000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [selectedSymbol]);

  const bids = book?.bids || [];
  const asks = book?.asks || [];
  const maxLot = Math.max(...bids.map((b) => b.lots), ...asks.map((a) => a.lots), 1);

  const topBid = bids[0]?.price ? parseFloat(bids[0].price) : 0;
  const topAsk = asks[0]?.price ? parseFloat(asks[0].price) : 0;
  const spread = topAsk > 0 && topBid > 0 ? topAsk - topBid : 0;
  const spreadPct = topBid > 0 ? ((spread / topBid) * 100).toFixed(2) : '0.00';

  const totalBidLots = bids.reduce((acc, b) => acc + b.lots, 0);
  const totalAskLots = asks.reduce((acc, a) => acc + a.lots, 0);
  const totalLots = totalBidLots + totalAskLots;
  const bidRatio = totalLots > 0 ? (totalBidLots / totalLots) * 100 : 50;

  return (
    <div className="space-y-4 font-mono text-[13px]">
      {/* Interactive API Spec Drawer */}
      <ApiSpecDrawer
        method="GET"
        endpoint="/v1/books/:symbol"
        queryParams={`/v1/quotes/${selectedSymbol} · /v1/books/snapshot/${selectedSymbol}`}
        useCaseTitle="Market Liquidity, Spread & Slippage Estimation"
        useCaseDescription="Provides multi-tier Level 2 Bid/Ask matrix with live cumulative depth. Essential for quantitative market making, limit-order queue estimation, measuring instantaneous liquidity imbalance, and calculating market impact before executing large block trades."
        curlCommand={`curl -s "http://127.0.0.1:8000/v1/books/${selectedSymbol}"`}
        responsePreview={`{
  "symbol": "${selectedSymbol}",
  "book": {
    "bids": [{ "price": "${topBid || '6700'}", "lots": ${bids[0]?.lots || 137940} }],
    "asks": [{ "price": "${topAsk || '6725'}", "lots": ${asks[0]?.lots || 47} }]
  }
}`}
      />

      {/* Top Metrics Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-[#000000] border border-[#202020] p-3.5 rounded-[2px]">
        <div>
          <div className="text-[#7e7e7e] text-[11px]">SYMBOL</div>
          <div className="text-[#eeeeee] font-bold text-[15px]">
            {selectedSymbol} <span className="text-[#7e7e7e] font-normal text-[12px]">(IDX Equity)</span>
          </div>
        </div>
        <div>
          <div className="text-[#7e7e7e] text-[11px]">LAST PRICE / CHANGE</div>
          <div className="text-[#eeeeee] font-bold text-[15px]">
            Rp {quote?.last ? parseInt(quote.last, 10).toLocaleString() : '—'}
            {quote?.change && (
              <span className={`text-[12px] ml-2 ${quote.change.startsWith('+') ? 'text-[#eeeeee]' : 'text-[#da5c2c]'}`}>
                {quote.change} ({quote.change_pct || ''})
              </span>
            )}
          </div>
        </div>
        <div>
          <div className="text-[#7e7e7e] text-[11px]">BID / ASK SPREAD</div>
          <div className="text-[#eeeeee] font-bold text-[15px]">
            {spread > 0 ? (
              <>Rp {spread.toLocaleString()} <span className="text-[#7e7e7e] font-normal text-[11px]">({spreadPct}%)</span></>
            ) : (
              '—'
            )}
          </div>
        </div>
        <div className="flex items-center sm:justify-end">
          <div className="flex items-center gap-1 bg-[#111111] p-1 border border-[#202020] rounded-[2px]">
            <button
              onClick={() => setFormat('proto')}
              className={`px-2.5 py-1 text-[11px] rounded-[2px] cursor-pointer transition-colors ${
                format === 'proto' ? 'bg-[#191919] text-[#eeeeee] font-bold border border-[#3a3a3a]' : 'text-[#7e7e7e] hover:text-[#eeeeee]'
              }`}
            >
              OrderBookBody (Tag 6)
            </button>
            <button
              onClick={() => setFormat('pipe')}
              className={`px-2.5 py-1 text-[11px] rounded-[2px] cursor-pointer transition-colors ${
                format === 'pipe' ? 'bg-[#191919] text-[#eeeeee] font-bold border border-[#3a3a3a]' : 'text-[#7e7e7e] hover:text-[#eeeeee]'
              }`}
            >
              Pipe (#O Tag 10)
            </button>
          </div>
        </div>
      </div>

      {loading && !book ? (
        <div className="border border-[#202020] bg-[#111111] p-8 text-center text-[#7e7e7e] text-[12px]">
          Loading real Level 2 orderbook depth for {selectedSymbol}...
        </div>
      ) : bids.length === 0 && asks.length === 0 ? (
        <div className="border border-[#202020] bg-[#111111] p-8 text-center text-[#7e7e7e] text-[12px] space-y-2">
          <div className="text-[#eeeeee] font-bold">NO ACTIVE ORDER BOOK DEPTH</div>
          <div>No active depth levels returned for {selectedSymbol}.</div>
        </div>
      ) : (
        <>
          {/* Dual Ladder Table */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Bids Table */}
            <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
              <div className="bg-[#191919] border-b border-[#202020] px-4 py-2.5 flex items-center justify-between text-[#b4b4b4] text-[12px]">
                <span className="text-[#eeeeee] font-bold">BIDS (BUY)</span>
                <span className="text-[#7e7e7e]">{totalBidLots.toLocaleString()} lots</span>
              </div>
              <div className="divide-y divide-[#202020]">
                {bids.map((b, i) => {
                  const widthPct = Math.min((b.lots / maxLot) * 100, 100);
                  return (
                    <div key={i} className="relative flex items-center justify-between px-4 py-2 hover:bg-[#191919] transition-colors">
                      <div
                        className="absolute right-0 top-0 bottom-0 bg-[#2a7fff] opacity-15 pointer-events-none"
                        style={{ width: `${widthPct}%` }}
                      />
                      <span className="font-bold text-[#eeeeee] relative z-10">
                        Rp {parseInt(b.price, 10).toLocaleString()}
                      </span>
                      <span className="text-[#b4b4b4] relative z-10">
                        {b.lots.toLocaleString()} lots
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Asks Table */}
            <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
              <div className="bg-[#191919] border-b border-[#202020] px-4 py-2.5 flex items-center justify-between text-[#b4b4b4] text-[12px]">
                <span className="text-[#eeeeee] font-bold">ASKS (SELL)</span>
                <span className="text-[#7e7e7e]">{totalAskLots.toLocaleString()} lots</span>
              </div>
              <div className="divide-y divide-[#202020]">
                {asks.map((a, i) => {
                  const widthPct = Math.min((a.lots / maxLot) * 100, 100);
                  return (
                    <div key={i} className="relative flex items-center justify-between px-4 py-2 hover:bg-[#191919] transition-colors">
                      <div
                        className="absolute left-0 top-0 bottom-0 bg-[#da5c2c] opacity-15 pointer-events-none"
                        style={{ width: `${widthPct}%` }}
                      />
                      <span className="font-bold text-[#eeeeee] relative z-10">
                        Rp {parseInt(a.price, 10).toLocaleString()}
                      </span>
                      <span className="text-[#b4b4b4] relative z-10">
                        {a.lots.toLocaleString()} lots
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Imbalance Meter */}
          <div className="bg-[#000000] border border-[#202020] p-3 rounded-[2px] font-mono text-[12px]">
            <div className="flex justify-between text-[#7e7e7e] mb-1.5">
              <span>Depth Balance: <strong className="text-[#eeeeee]">{bidRatio.toFixed(1)}% Bids</strong></span>
              <span><strong className="text-[#eeeeee]">{(100 - bidRatio).toFixed(1)}% Asks</strong></span>
            </div>
            <div className="w-full h-2.5 bg-[#111111] border border-[#202020] rounded-[1px] overflow-hidden flex">
              <div className="bg-[#2a7fff] h-full transition-all duration-300" style={{ width: `${bidRatio}%` }} />
              <div className="bg-[#da5c2c] h-full transition-all duration-300" style={{ width: `${100 - bidRatio}%` }} />
            </div>
          </div>
        </>
      )}
    </div>
  );
};
