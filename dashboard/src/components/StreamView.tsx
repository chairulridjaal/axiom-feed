import React, { useState, useEffect, useRef } from 'react';
import { createLiveWebSocket, fetchLiveTrades, getStoredBackendUrl } from '../services/api';
import { Trade } from '../types/datafeed';
import { ApiSpecDrawer } from './ApiSpecDrawer';

interface StreamViewProps {
  selectedSymbol: string;
}

export const StreamView: React.FC<StreamViewProps> = ({ selectedSymbol }) => {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [subscribeQuery, setSubscribeQuery] = useState<string>(selectedSymbol);
  const [statusMessage, setStatusMessage] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [wsConnected, setWsConnected] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const wsHandleRef = useRef<{ close: () => void; send: (data: string) => void; isConnected: () => boolean } | null>(null);

  // Sync selected symbol to input
  useEffect(() => {
    setSubscribeQuery(selectedSymbol);
  }, [selectedSymbol]);

  // Load initial trades and connect to WebSocket
  useEffect(() => {
    let mounted = true;
    setIsLoading(true);

    // 1. Fetch recent trades from REST
    const loadRecentTrades = async () => {
      const recent = await fetchLiveTrades(selectedSymbol, 50, getStoredBackendUrl());
      if (mounted) {
        setTrades(recent);
        setIsLoading(false);
      }
    };
    loadRecentTrades();

    // 2. Connect to live WebSocket
    const ws = createLiveWebSocket(
      (msg) => {
        if (msg.type === 'subscribed') {
          setStatusMessage({
            type: 'ok',
            text: `Subscribed: ${msg.symbols?.join(', ')} (${msg.kinds?.join(', ')})`,
          });
        } else if (msg.type === 'error') {
          setStatusMessage({
            type: 'err',
            text: `Backend Error: ${msg.message || 'Subscription rejected'}`,
          });
        } else if (msg.symbol && msg.price) {
          // Live real trade message
          const newTrade: Trade = {
            symbol: msg.symbol,
            price: msg.price.toString(),
            volume: Number(msg.volume || msg.lots || 0),
            side: (msg.side || 'BUY').toUpperCase() as any,
            board: (msg.board || 'RG').toUpperCase() as any,
            ts: msg.ts || msg.time || new Date().toISOString(),
            seq: Number(msg.seq || Date.now()),
            change: msg.change?.toString(),
            change_pct: msg.change_pct?.toString(),
          };
          setTrades((prev) => [newTrade, ...prev.slice(0, 49)]);
        }
      },
      () => {
        setWsConnected(true);
        // Subscribe to selected symbol
        ws.send(JSON.stringify({
          action: 'subscribe',
          symbols: [selectedSymbol],
          kinds: ['trades', 'quotes'],
        }));
      },
      () => setWsConnected(false),
      () => setWsConnected(false),
      getStoredBackendUrl()
    );

    wsHandleRef.current = ws;

    return () => {
      mounted = false;
      ws.close();
    };
  }, [selectedSymbol]);

  const handleSubscribe = () => {
    const syms = subscribeQuery.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
    if (wsHandleRef.current && wsHandleRef.current.isConnected()) {
      wsHandleRef.current.send(JSON.stringify({
        action: 'subscribe',
        symbols: syms,
        kinds: ['trades', 'quotes'],
      }));
      setStatusMessage({
        type: 'ok',
        text: `Subscription sent for: ${syms.join(', ')}`,
      });
    } else {
      setStatusMessage({
        type: 'err',
        text: `WebSocket disconnected. Reconnecting...`,
      });
    }
  };

  const handleTestWildcardTrades = () => {
    setSubscribeQuery('*');
    if (wsHandleRef.current && wsHandleRef.current.isConnected()) {
      wsHandleRef.current.send(JSON.stringify({
        action: 'subscribe',
        symbols: ['*'],
        kinds: ['trades'],
      }));
    }
    setStatusMessage({
      type: 'ok',
      text: `Subscribed wildcard '*' for all market running trades.`,
    });
  };

  const handleTestWildcardQuotes = () => {
    setSubscribeQuery('*');
    if (wsHandleRef.current && wsHandleRef.current.isConnected()) {
      wsHandleRef.current.send(JSON.stringify({
        action: 'subscribe',
        symbols: ['*'],
        kinds: ['quotes', 'books'],
      }));
    } else {
      setStatusMessage({
        type: 'err',
        text: `Error 400: '*' only supported for trades (running_trade_batch). Quotes and books require explicit symbols.`,
      });
    }
  };

  return (
    <div className="space-y-4 font-mono text-[13px]">
      {/* Interactive API Spec Drawer */}
      <ApiSpecDrawer
        method="WS"
        endpoint="/v1/stream"
        queryParams="?token=$API_KEY (or REST fallback GET /v1/trades)"
        useCaseTitle="Ultra-Low Latency Execution Tape & Algorithmic Fills"
        useCaseDescription="Delivers sub-millisecond execution tick events from IDX over WebSocket. Used by algorithmic trading engines to track real-time trade board liquidity (RG Regular, TN Cash, NG Negotiated), calculate volume-weighted average price (VWAP) benchmarks, and detect aggressive institutional market orders."
        curlCommand={`websocat "ws://127.0.0.1:8000/v1/stream?token=$API_KEY" <<< '{"action":"subscribe","symbols":["${selectedSymbol}"],"kinds":["trades"]}'`}
        responsePreview={`{
  "symbol": "${selectedSymbol}",
  "price": "6675",
  "volume": 2500,
  "side": "BUY",
  "board": "RG",
  "seq": 48291
}`}
      />

      {/* Control Strip */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 bg-[#000000] border border-[#202020] rounded-[2px]">
        <div className="flex items-center gap-2 flex-1">
          <span className="text-[#7e7e7e]">Subscribe:</span>
          <input
            type="text"
            value={subscribeQuery}
            onChange={(e) => setSubscribeQuery(e.target.value)}
            className="terminal-input flex-1 py-1 px-2.5 text-[12px]"
            placeholder="e.g. BBCA, BBRI or *"
          />
          <button onClick={handleSubscribe} className="btn-primary py-1 px-3 text-[12px] cursor-pointer">
            Subscribe →
          </button>
          <span className="flex items-center gap-1.5 text-[11px] text-[#7e7e7e] ml-2">
            <span className={`w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-[#da5c2c]' : 'bg-[#606060]'}`} />
            {wsConnected ? 'WS STREAM ACTIVE' : 'WS CONNECTING...'}
          </span>
        </div>

        {/* Guardrail tests */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleTestWildcardTrades}
            className="btn-action-sm text-[11px] text-[#eeeeee]"
          >
            Test '*' for Trades →
          </button>
          <button
            onClick={handleTestWildcardQuotes}
            className="btn-action-sm text-[11px] text-[#da5c2c]"
          >
            Test '*' for Quotes (400) →
          </button>
        </div>
      </div>

      {/* Status banner if active */}
      {statusMessage && (
        <div
          className={`p-2.5 rounded-[2px] font-mono text-[12px] border ${
            statusMessage.type === 'ok'
              ? 'bg-[#191919] border-[#3a3a3a] text-[#eeeeee]'
              : 'bg-[#191919] border-[#da5c2c] text-[#da5c2c]'
          }`}
        >
          {statusMessage.text}
        </div>
      )}

      {/* Clean Monospaced Table or Empty State */}
      <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
        {trades.length === 0 ? (
          <div className="p-8 text-center space-y-3">
            <div className="text-[#eeeeee] font-bold text-[14px]">
              {isLoading ? 'Connecting to live trade feed...' : 'NO ACTIVE RUNNING TRADES IN BUFFER'}
            </div>
            <p className="text-[#7e7e7e] text-[12px] max-w-lg mx-auto leading-relaxed">
              {isLoading
                ? 'Initializing WebSocket connection to axiom-feed...'
                : 'IDX trading hours are Monday–Friday, 09:00–16:15 WIB (UTC+7). Running trades stream live tick-by-tick over WebSocket during market session. Outside market hours, tick queue remains idle.'}
            </p>
            <div className="flex items-center justify-center gap-2 pt-2">
              <span className="text-[11px] px-2 py-0.5 rounded-[2px] bg-[#191919] border border-[#202020] text-[#b4b4b4]">
                GET /v1/trades?symbols={selectedSymbol} → []
              </span>
              <span className="text-[11px] px-2 py-0.5 rounded-[2px] bg-[#191919] border border-[#202020] text-[#da5c2c]">
                WS /v1/stream (Ready)
              </span>
            </div>
          </div>
        ) : (
          <table className="w-full text-left font-mono text-[13px]">
            <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
              <tr>
                <th className="py-2.5 px-4 font-normal">TIMESTAMP (WIB)</th>
                <th className="py-2.5 px-4 font-normal">SYMBOL</th>
                <th className="py-2.5 px-4 font-normal text-right">PRICE (RP)</th>
                <th className="py-2.5 px-4 font-normal text-right">VOLUME (LOTS)</th>
                <th className="py-2.5 px-4 font-normal text-right">SIDE</th>
                <th className="py-2.5 px-4 font-normal text-right">BOARD</th>
                <th className="py-2.5 px-4 font-normal text-right">SEQ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
              {trades.map((t, idx) => {
                const isBuy = t.side === 'BUY';
                return (
                  <tr key={idx} className="hover:bg-[#191919] transition-colors">
                    <td className="py-2.5 px-4 text-[#7e7e7e]">{t.ts}</td>
                    <td className="py-2.5 px-4 font-bold text-[#eeeeee]">{t.symbol}</td>
                    <td className="py-2.5 px-4 text-right font-bold text-[#eeeeee]">
                      {parseInt(t.price, 10).toLocaleString()}
                    </td>
                    <td className="py-2.5 px-4 text-right text-[#b4b4b4]">
                      {t.volume.toLocaleString()}
                    </td>
                    <td className="py-2.5 px-4 text-right">
                      <span
                        className={`text-[11px] px-1.5 py-0.5 rounded-[2px] ${
                          isBuy ? 'text-[#eeeeee] bg-[#202020]' : 'text-[#7e7e7e] bg-[#000000]'
                        }`}
                      >
                        {t.side}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-right text-[#7e7e7e]">{t.board}</td>
                    <td className="py-2.5 px-4 text-right text-[#7e7e7e]">#{t.seq}</td>
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
