import React, { useState } from 'react';

export type ConsoleTab = 
  | 'stream' 
  | 'orderbook' 
  | 'candles' 
  | 'movers' 
  | 'brokers' 
  | 'sectors' 
  | 'fundamentals' 
  | 'calendars'
  | 'seasonality'
  | 'proto' 
  | 'telemetry';

interface ConsoleHeaderProps {
  activeTab: ConsoleTab;
  onSelectTab: (tab: ConsoleTab) => void;
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
  isLive: boolean;
  backendUrl: string;
  onUpdateBackendUrl: (url: string) => void;
  apiKey: string;
  onUpdateApiKey: (key: string) => void;
  onCheckHealth: () => void;
}

export const ConsoleHeader: React.FC<ConsoleHeaderProps> = ({
  activeTab,
  onSelectTab,
  selectedSymbol,
  onSelectSymbol,
  isLive,
  backendUrl,
  onUpdateBackendUrl,
  apiKey,
  onUpdateApiKey,
  onCheckHealth,
}) => {
  const [isEditingUrl, setIsEditingUrl] = useState<boolean>(false);
  const [urlDraft, setUrlDraft] = useState<string>(backendUrl);
  const [isEditingKey, setIsEditingKey] = useState<boolean>(false);
  const [keyDraft, setKeyDraft] = useState<string>(apiKey);

  const tabs: { id: ConsoleTab; label: string }[] = [
    { id: 'stream', label: '1. Tape & Stream' },
    { id: 'orderbook', label: '2. Order Book (L2)' },
    { id: 'candles', label: '3. Candles & Charts' },
    { id: 'movers', label: '4. Market Movers' },
    { id: 'brokers', label: '5. Broker Flow' },
    { id: 'sectors', label: '6. Sectors' },
    { id: 'fundamentals', label: '7. Financials' },
    { id: 'calendars', label: '8. Calendars' },
    { id: 'seasonality', label: '9. Seasonality' },
    { id: 'proto', label: '10. Protobuf Wire' },
    { id: 'telemetry', label: '11. Telemetry' },
  ];

  const symbols = ['BBCA', 'BBRI', 'TLKM', 'BMRI', 'ASII', 'GOTO', 'IHSG'];

  const handleSaveUrl = (e: React.FormEvent) => {
    e.preventDefault();
    if (urlDraft.trim()) {
      onUpdateBackendUrl(urlDraft.trim());
      setIsEditingUrl(false);
    }
  };

  const handleSaveKey = (e: React.FormEvent) => {
    e.preventDefault();
    onUpdateApiKey(keyDraft.trim());
    setIsEditingKey(false);
  };

  return (
    <div className="border-b border-[#202020] bg-[#111111] select-none">
      {/* Top Controls Bar: Context Info (Left) + Symbols & Endpoint URL (Right) */}
      <div className="px-4 py-2 border-b border-[#202020] bg-[#000000] flex flex-wrap items-center justify-between gap-2 text-[11px] font-mono">
        <div className="flex items-center gap-2 text-[#7e7e7e]">
          <span className="text-[#da5c2c] font-bold">API EXPLORER</span>
          <span className="text-[#3a3a3a]">/</span>
          <span className="text-[#eeeeee]">IDX MARKET DATA</span>
          <span className="text-[#3a3a3a]">/</span>
          <span className="text-[#da5c2c] font-bold">{selectedSymbol}</span>
        </div>

        {/* Right: Symbol Selector & Backend URL Controller */}
        <div className="flex items-center gap-2.5">
          {/* Symbol buttons */}
          <div className="flex items-center gap-1 bg-[#111111] p-0.5 border border-[#202020] rounded-[2px]">
            {symbols.map((s) => (
              <button
                key={s}
                onClick={() => onSelectSymbol(s)}
                className={`px-2 py-0.5 font-mono text-[11px] rounded-[2px] transition-colors cursor-pointer ${
                  selectedSymbol === s
                    ? 'bg-[#191919] text-[#eeeeee] font-bold border border-[#3a3a3a]'
                    : 'text-[#7e7e7e] hover:text-[#eeeeee]'
                }`}
              >
                {s}
              </button>
            ))}
          </div>

          {/* Backend Target URL Button / Form */}
          {isEditingUrl ? (
            <form onSubmit={handleSaveUrl} className="flex items-center gap-1">
              <input
                type="text"
                value={urlDraft}
                onChange={(e) => setUrlDraft(e.target.value)}
                className="terminal-input py-0.5 px-2 text-[11px] w-36"
                placeholder="http://127.0.0.1:8000"
                autoFocus
              />
              <button type="submit" className="btn-primary py-0.5 px-2 text-[10px] cursor-pointer">
                Set
              </button>
              <button
                type="button"
                onClick={() => setIsEditingUrl(false)}
                className="btn-ghost py-0.5 px-2 text-[10px] cursor-pointer"
              >
                ✕
              </button>
            </form>
          ) : (
            <div className="flex items-center gap-1.5 bg-[#111111] border border-[#202020] px-2 py-0.5 rounded-[2px] font-mono text-[11px]">
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isLive ? 'bg-[#da5c2c]' : 'bg-[#606060]'
                }`}
              />
              <button
                onClick={() => {
                  setUrlDraft(backendUrl);
                  setIsEditingUrl(true);
                }}
                className="text-[#b4b4b4] hover:text-[#eeeeee] cursor-pointer underline"
                title="Click to edit backend URL"
              >
                {backendUrl.replace(/^https?:\/\//, '')}
              </button>
              <button
                onClick={onCheckHealth}
                className="text-[#7e7e7e] hover:text-[#eeeeee] ml-0.5 cursor-pointer"
                title="Re-check connection"
              >
                ↻
              </button>
            </div>
          )}

          {/* API Key Button / Form */}
          {isEditingKey ? (
            <form onSubmit={handleSaveKey} className="flex items-center gap-1">
              <input
                type="password"
                value={keyDraft}
                onChange={(e) => setKeyDraft(e.target.value)}
                className="terminal-input py-0.5 px-2 text-[11px] w-36"
                placeholder="X-API-Key"
                autoFocus
              />
              <button type="submit" className="btn-primary py-0.5 px-2 text-[10px] cursor-pointer">
                Set
              </button>
              <button
                type="button"
                onClick={() => setIsEditingKey(false)}
                className="btn-ghost py-0.5 px-2 text-[10px] cursor-pointer"
              >
                ✕
              </button>
            </form>
          ) : (
            <div className="flex items-center gap-1.5 bg-[#111111] border border-[#202020] px-2 py-0.5 rounded-[2px] font-mono text-[11px]">
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  apiKey ? 'bg-[#da5c2c]' : 'bg-[#606060]'
                }`}
              />
              <button
                onClick={() => {
                  setKeyDraft(apiKey);
                  setIsEditingKey(true);
                }}
                className="text-[#b4b4b4] hover:text-[#eeeeee] cursor-pointer underline"
                title="Click to edit API key"
              >
                {apiKey ? `KEY ••${apiKey.slice(-4)}` : 'NO KEY'}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Dedicated Domain Tabs Row — Full width with clean horizontal scroll */}
      <div className="px-4 flex items-center gap-1 overflow-x-auto scrollbar-none -mb-[1px]">
        {tabs.map((t) => {
          const isActive = activeTab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => onSelectTab(t.id)}
              className={`py-3 px-3.5 font-mono text-[12px] tracking-tight transition-colors border-b-2 whitespace-nowrap cursor-pointer shrink-0 ${
                isActive
                  ? 'border-[#eeeeee] text-[#eeeeee] font-bold'
                  : 'border-transparent text-[#7e7e7e] hover:text-[#eeeeee] hover:border-[#3a3a3a]'
              }`}
            >
              {t.label}
            </button>
          );
        })}
      </div>
    </div>
  );
};
