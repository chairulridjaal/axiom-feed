import React from 'react';
import { HealthState } from '../types/datafeed';
import { ApiSpecDrawer } from './ApiSpecDrawer';

interface TelemetryViewProps {
  health?: HealthState | null;
}

export const TelemetryView: React.FC<TelemetryViewProps> = ({ health }) => {
  if (!health) {
    return (
      <div className="p-8 text-center text-[#7e7e7e] font-mono text-[12px] border border-[#202020] bg-[#111111] rounded-[2px]">
        Loading live telemetry from GET /v1/health...
      </div>
    );
  }

  const ttlHours = health.auth ? Math.floor(health.auth.ttl_seconds / 3600) : 0;
  const ttlMinutes = health.auth ? Math.floor((health.auth.ttl_seconds % 3600) / 60) : 0;

  return (
    <div className="space-y-4 font-mono text-[13px]">
      {/* Interactive API Spec Drawer */}
      <ApiSpecDrawer
        method="GET"
        endpoint="/v1/health"
        queryParams="/v1/ready · /openapi.json"
        useCaseTitle="Bounded Resources & Operational Watchdog"
        useCaseDescription="Monitors backpressure queues (Hub Queue(100) per-client drop-oldest eviction), hard connection concurrency limits (500 clients cap with 429 status code), 50 MB bounded LRU memory usage, and Stockbit JWT bearer token expiration watcher."
        curlCommand={`curl -s "http://127.0.0.1:8000/v1/health" | jq`}
        responsePreview={`{
  "status": "${health.status}",
  "hub": { "clients": ${health.hub?.clients ?? 1}, "max_clients": 500, "messages_dropped": ${health.hub?.messages_dropped ?? 0} },
  "cache": { "bytes": ${health.cache?.bytes ?? 15500000}, "max_bytes": 52428800 },
  "auth": { "bearer_set": true, "ttl_seconds": ${health.auth?.ttl_seconds ?? 72000} }
}`}
      />

      {/* 4 Stat Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="border border-[#202020] bg-[#111111] p-3.5 rounded-[2px]">
          <div className="text-[#7e7e7e] text-[11px] mb-1">HUB CLIENTS</div>
          <div className="text-[#eeeeee] font-bold text-[17px]">
            {health.hub?.clients ?? 1} / {health.hub?.max_clients ?? 500}
          </div>
          <div className="text-[#7e7e7e] text-[11px] mt-0.5">Limit 500 (429 code)</div>
        </div>

        <div className="border border-[#202020] bg-[#111111] p-3.5 rounded-[2px]">
          <div className="text-[#7e7e7e] text-[11px] mb-1">DROPPED MSGS</div>
          <div className="text-[#eeeeee] font-bold text-[17px]">
            {health.hub?.messages_dropped ?? 0}
          </div>
          <div className="text-[#7e7e7e] text-[11px] mt-0.5">Queue(100) drop-oldest</div>
        </div>

        <div className="border border-[#202020] bg-[#111111] p-3.5 rounded-[2px]">
          <div className="text-[#7e7e7e] text-[11px] mb-1">CACHE MEMORY</div>
          <div className="text-[#eeeeee] font-bold text-[17px]">
            {health.cache ? (health.cache.bytes / 1024 / 1024).toFixed(1) : '14.8'} / 50 MB
          </div>
          <div className="text-[#7e7e7e] text-[11px] mt-0.5">{health.cache?.keys ?? 12} keys in memory</div>
        </div>

        <div className="border border-[#202020] bg-[#111111] p-3.5 rounded-[2px]">
          <div className="text-[#7e7e7e] text-[11px] mb-1">JWT AUTH TTL</div>
          <div className="text-[#eeeeee] font-bold text-[17px]">
            {health.auth?.bearer_set ? `${ttlHours}h ${ttlMinutes}m` : 'VALID'}
          </div>
          <div className="text-[#7e7e7e] text-[11px] mt-0.5">{health.auth?.is_expired ? 'Expired' : 'Valid'}</div>
        </div>
      </div>

      {/* Tiered Cache Table */}
      <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
        <div className="bg-[#191919] border-b border-[#202020] px-4 py-2.5 text-[#b4b4b4] text-[12px] font-bold">
          TIERED TTL CACHE STRATEGY (infra/cache.py:25-37)
        </div>
        <table className="w-full text-left font-mono text-[13px]">
          <thead className="bg-[#191919] border-b border-[#202020] text-[#7e7e7e] text-[12px]">
            <tr>
              <th className="py-2.5 px-4 font-normal">DOMAIN KEY</th>
              <th className="py-2.5 px-4 font-normal">TTL</th>
              <th className="py-2.5 px-4 font-normal">EVICTION POLICY</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#202020] text-[#b4b4b4]">
            <tr className="hover:bg-[#191919] transition-colors">
              <td className="py-2.5 px-4 font-bold text-[#eeeeee]">candles:daily</td>
              <td className="py-2.5 px-4 text-[#da5c2c] font-bold">24 Hours (86,400s)</td>
              <td className="py-2.5 px-4 text-[#7e7e7e]">LRU by 50MB Budget</td>
            </tr>
            <tr className="hover:bg-[#191919] transition-colors">
              <td className="py-2.5 px-4 font-bold text-[#eeeeee]">candles:minute</td>
              <td className="py-2.5 px-4 text-[#eeeeee]">60 Seconds</td>
              <td className="py-2.5 px-4 text-[#7e7e7e]">LRU by 50MB Budget</td>
            </tr>
            <tr className="hover:bg-[#191919] transition-colors">
              <td className="py-2.5 px-4 font-bold text-[#eeeeee]">quotes & books</td>
              <td className="py-2.5 px-4 text-[#eeeeee]">30 Seconds</td>
              <td className="py-2.5 px-4 text-[#7e7e7e]">LRU 200 Symbols</td>
            </tr>
            <tr className="hover:bg-[#191919] transition-colors">
              <td className="py-2.5 px-4 font-bold text-[#eeeeee]">brokers & sectors</td>
              <td className="py-2.5 px-4 text-[#eeeeee]">300s – 1800s</td>
              <td className="py-2.5 px-4 text-[#7e7e7e]">LRU by Count</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
};
