import React, { useState } from 'react';

interface BackendOfflineProps {
  backendUrl: string;
  onUpdateBackendUrl: (newUrl: string) => void;
  onRetry: () => void;
  isChecking: boolean;
  errorMessage?: string;
}

export const BackendOffline: React.FC<BackendOfflineProps> = ({
  backendUrl,
  onUpdateBackendUrl,
  onRetry,
  isChecking,
  errorMessage,
}) => {
  const [urlInput, setUrlInput] = useState<string>(backendUrl);
  const [isEditing, setIsEditing] = useState<boolean>(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (urlInput.trim()) {
      onUpdateBackendUrl(urlInput.trim());
      setIsEditing(false);
    }
  };

  return (
    <div className="p-8 sm:p-12 text-center max-w-[700px] mx-auto space-y-6 font-mono">
      {/* Offline Status Badge */}
      <div className="inline-flex items-center gap-2 px-3 py-1 bg-[#191919] border border-[#da5c2c] rounded-[2px] text-[#da5c2c] text-[12px] font-bold">
        <span className="w-2 h-2 rounded-full bg-[#da5c2c] animate-pulse" />
        BACKEND OFFLINE · NO CONNECTION
      </div>

      {/* Main Message */}
      <div className="space-y-2">
        <h2 className="text-[20px] sm:text-[24px] font-bold text-[#eeeeee]">
          Live Backend Service Required
        </h2>
        <p className="text-[13px] text-[#b4b4b4] leading-relaxed">
          The exploration dashboard requires a live connection to the <code className="text-[#eeeeee]">axiom-feed</code> backend service to inspect market data, stream trades, and dissect wire protocols.
        </p>
      </div>

      {/* Target Backend URL Config Bar */}
      <div className="p-4 bg-[#000000] border border-[#202020] rounded-[2px] text-left space-y-3">
        <div className="flex items-center justify-between text-[11px] text-[#7e7e7e]">
          <span>TARGET BACKEND ENDPOINT</span>
          <button
            onClick={() => setIsEditing(!isEditing)}
            className="text-[#eeeeee] underline hover:text-[#da5c2c] cursor-pointer"
          >
            {isEditing ? 'Cancel' : 'Change URL'}
          </button>
        </div>

        {isEditing ? (
          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              className="terminal-input flex-1 py-1.5 px-3 text-[13px]"
              placeholder="http://localhost:8000"
              autoFocus
            />
            <button type="submit" className="btn-primary py-1.5 px-4 text-[12px] cursor-pointer">
              Save & Connect
            </button>
          </form>
        ) : (
          <div className="flex items-center justify-between">
            <code className="text-[#eeeeee] font-bold text-[14px] bg-[#111111] px-2.5 py-1 rounded-[2px] border border-[#202020]">
              {backendUrl}
            </code>
            <button
              onClick={onRetry}
              disabled={isChecking}
              className="btn-primary py-1.5 px-4 text-[12px] cursor-pointer"
            >
              {isChecking ? 'Checking...' : 'Retry Connection →'}
            </button>
          </div>
        )}

        {errorMessage && (
          <div className="text-[#da5c2c] text-[11px] pt-1">
            Status: {errorMessage}
          </div>
        )}
      </div>

      {/* Startup Commands Box */}
      <div className="p-4 bg-[#191919] border border-[#202020] rounded-[2px] text-left space-y-3">
        <div className="text-[#7e7e7e] text-[11px] font-bold uppercase tracking-wider">
          How to start the backend service
        </div>

        <div className="space-y-2 text-[12px]">
          <div>
            <span className="text-[#7e7e7e]">Option 1 — Python dev server:</span>
            <pre className="mt-1 p-2.5 bg-[#000000] border border-[#202020] rounded-[2px] text-[#eeeeee] overflow-x-auto">
cd services/api-py && uv run uvicorn app.main:app --reload --port 8000
            </pre>
          </div>

          <div>
            <span className="text-[#7e7e7e]">Option 2 — Docker Compose:</span>
            <pre className="mt-1 p-2.5 bg-[#000000] border border-[#202020] rounded-[2px] text-[#eeeeee] overflow-x-auto">
docker compose up --build
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
};
