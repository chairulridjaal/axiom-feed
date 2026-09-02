/**
 * Axiom Feed — Interactive Market Data & API Exploration Dashboard
 * 
 * Clean, lightweight, 100% real data explorer covering all 29 endpoints.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { ConsoleHeader, ConsoleTab } from './components/ConsoleHeader';
import { StreamView } from './components/StreamView';
import { OrderbookView } from './components/OrderbookView';
import { CandlesView } from './components/CandlesView';
import { MarketMoversView } from './components/MarketMoversView';
import { BrokersView } from './components/BrokersView';
import { SectorsView } from './components/SectorsView';
import { FundamentalsView } from './components/FundamentalsView';
import { CalendarsView } from './components/CalendarsView';
import { SeasonalityView } from './components/SeasonalityView';
import { ProtoView } from './components/ProtoView';
import { TelemetryView } from './components/TelemetryView';
import { BackendOffline } from './components/BackendOffline';
import { checkBackendHealth, getStoredBackendUrl, setStoredBackendUrl } from './services/api';
import { HealthState } from './types/datafeed';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ConsoleTab>('stream');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BBCA');
  const [backendUrl, setBackendUrl] = useState<string>(getStoredBackendUrl());
  const [isLive, setIsLive] = useState<boolean>(true);
  const [isChecking, setIsChecking] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | undefined>();
  const [healthData, setHealthData] = useState<HealthState | null>(null);

  const verifyHealth = useCallback(async (url: string = backendUrl) => {
    setIsChecking(true);
    const res = await checkBackendHealth(url);
    setIsLive(res.isLive);
    if (res.isLive) {
      setHealthData(res.data || null);
      setErrorMessage(undefined);
    } else {
      setHealthData(null);
      setErrorMessage(res.error || 'Connection refused');
    }
    setIsChecking(false);
  }, [backendUrl]);

  useEffect(() => {
    verifyHealth(backendUrl);
    const interval = setInterval(() => verifyHealth(backendUrl), 5000);
    return () => clearInterval(interval);
  }, [backendUrl, verifyHealth]);

  const handleUpdateBackendUrl = (newUrl: string) => {
    setStoredBackendUrl(newUrl);
    setBackendUrl(newUrl);
    verifyHealth(newUrl);
  };

  return (
    <div className="min-h-screen bg-[#000000] text-[#eeeeee] font-mono selection:bg-[#da5c2c] selection:text-[#eeeeee]">
      {/* 1. Header Bar */}
      <header className="sticky top-0 z-50 w-full bg-[#000000] border-b border-[#202020] h-13 px-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="#da5c2c">
            <polygon points="12 2 22 20 2 20" />
          </svg>
          <span className="font-bold text-[#eeeeee] text-[15px] tracking-tight">
            axiom-feed
          </span>
          <span className="text-[#606060] text-[11px] border-l border-[#202020] pl-2 ml-1 hidden sm:inline">
            IDX Market Data Explorer
          </span>
        </div>

        <div className="flex items-center gap-3 text-[11px] text-[#7e7e7e]">
          <span className="hidden md:inline">29 Endpoints Verified · Pure Real Data</span>
          <span className="flex items-center gap-1.5 text-[#b4b4b4]">
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                isLive ? 'bg-[#da5c2c]' : 'bg-[#606060]'
              }`}
            />
            {isLive ? 'CONNECTED' : 'OFFLINE'}
          </span>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-[1100px] mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* Central Product Console */}
        <section className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
          <ConsoleHeader
            activeTab={activeTab}
            onSelectTab={setActiveTab}
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            isLive={isLive}
            backendUrl={backendUrl}
            onUpdateBackendUrl={handleUpdateBackendUrl}
            onCheckHealth={() => verifyHealth(backendUrl)}
          />

          {!isLive ? (
            <BackendOffline
              backendUrl={backendUrl}
              onUpdateBackendUrl={handleUpdateBackendUrl}
              onRetry={() => verifyHealth(backendUrl)}
              isChecking={isChecking}
              errorMessage={errorMessage}
            />
          ) : (
            <div className="p-4 bg-[#111111]">
              {activeTab === 'stream' && <StreamView selectedSymbol={selectedSymbol} />}
              {activeTab === 'orderbook' && <OrderbookView selectedSymbol={selectedSymbol} />}
              {activeTab === 'candles' && <CandlesView selectedSymbol={selectedSymbol} />}
              {activeTab === 'movers' && <MarketMoversView />}
              {activeTab === 'brokers' && <BrokersView selectedSymbol={selectedSymbol} />}
              {activeTab === 'sectors' && <SectorsView />}
              {activeTab === 'fundamentals' && <FundamentalsView selectedSymbol={selectedSymbol} />}
              {activeTab === 'calendars' && <CalendarsView selectedSymbol={selectedSymbol} />}
              {activeTab === 'seasonality' && <SeasonalityView selectedSymbol={selectedSymbol} />}
              {activeTab === 'proto' && <ProtoView selectedSymbol={selectedSymbol} />}
              {activeTab === 'telemetry' && <TelemetryView health={healthData} />}
            </div>
          )}
        </section>

        {/* Minimal Footer Info */}
        <div className="flex flex-col sm:flex-row items-center justify-between text-[11px] text-[#606060] pt-2 border-t border-[#202020] gap-2">
          <span>axiom-feed · Standalone Market-Data Engine (Python + Rust)</span>
          <div className="flex items-center gap-3 text-[#7e7e7e]">
            <span>GET /v1/health</span>
            <span>·</span>
            <span>WS /v1/stream</span>
            <span>·</span>
            <span>docs/ENDPOINTS.md</span>
            <span>·</span>
            <a href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer" className="text-[#da5c2c] underline">
              OpenAPI /docs
            </a>
          </div>
        </div>
      </main>
    </div>
  );
};

export default App;
