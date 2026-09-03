/**
 * Type definitions matching shared/proto/datafeed.proto and services/api-py/app/domain/models.py
 */

export type SymbolCode = 'BBCA' | 'BBRI' | 'TLKM' | 'BMRI' | 'ASII' | 'GOTO' | 'BBNI' | 'ICBP' | 'UNVR' | 'IHSG';

export type Side = 'BUY' | 'SELL' | 'UNKNOWN';
export type Board = 'RG' | 'TN' | 'NG' | 'UNKNOWN';
export type Resolution = 'daily' | 'minute';

export interface Level {
  price: string;
  lots: number;
}

export interface Book {
  symbol: string;
  bids: Level[];
  asks: Level[];
  ts: string;
  seq: number;
}

export interface Trade {
  symbol: string;
  price: string;
  volume: number;
  side: Side;
  board: Board;
  ts: string;
  seq: number;
  change?: string;
  change_pct?: string;
}

export interface Quote {
  symbol: string;
  last: string;
  open?: string;
  high?: string;
  low?: string;
  prev_close?: string;
  change?: string;
  change_pct?: string;
  volume?: number;
  value?: string;
  freq?: number;
  avg?: string;
  ts: string;
  is_index: boolean;
}

export interface Candle {
  ts: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: number;
  value?: string;
  freq?: number;
}

export interface HealthState {
  status: 'healthy' | 'degraded' | 'offline';
  uptime_seconds: number;
  websocket_connected: boolean;
  entitlement_active: boolean;
  hub: {
    clients: number;
    max_clients: number;
    queue_size: number;
    messages_dropped: number;
    published: number;
  };
  cache: {
    keys: number;
    bytes: number;
    max_keys: number;
    max_bytes: number;
    hits: number;
    misses: number;
    evictions: number;
  };
  ingest: 'redis' | 'embedded';
  auth: {
    bearer_set: boolean;
    is_expired: boolean;
    ttl_seconds: number;
    user_id?: string;
  };
}

export interface HistoricalSlice {
  windowIndex: number;
  from: string;
  to: string;
  fromParam: string | number;
  toParam: string | number;
  resolution: Resolution;
  candleCount: number;
  cacheStatus: 'HIT' | 'MISS';
  sizeBytes: number;
}

export interface MoverItem {
  symbol: string;
  last: string;
  change: string;
  change_pct: string;
  volume?: number;
  value?: string;
  name?: string;
}

export interface BrokerItem {
  code: string;
  name: string;
  type: 'D' | 'F'; // Domestic vs Foreign
  buy_val: number;
  sell_val: number;
  net_val: number;
  buy_vol: number;
  sell_vol: number;
  top_stock: string;
  total_val: number;
  total_vol: number;
  total_freq: number;
}

export interface BrokerFlowEntry {
  broker_code: string;
  stock_code?: string;
  avg_price: number;
  lots: number;
  value: number;
  type?: string;
  freq?: number;
}

export interface BrokerSummary {
  symbol: string;
  status: string;
  avg_price: number;
  broker_accdist?: string;
  top_buyers: BrokerFlowEntry[];
  top_sellers: BrokerFlowEntry[];
}

export interface SubsectorItem {
  id: string;
  name: string;
  companies_count?: number;
}

export interface SectorCompany {
  symbol: string;
  name: string;
  last: string;
  change: string;
  change_pct: string;
  market_cap?: string;
  volume?: number;
}

export interface SectorItem {
  id: string;
  name: string;
  alias?: string;
  change_pct?: number;
  mc_val?: number;
  companies_count?: number;
  subsectors?: SubsectorItem[];
}

export interface CompanyProfile {
  symbol: string;
  name: string;
  sector?: string;
  subsector?: string;
  address?: string;
  email?: string;
  phone?: string;
  website?: string;
  listing_date?: string;
  description?: string;
}

export interface KeyStats {
  symbol: string;
  pe_ratio?: number;
  pe_ttm?: number;
  pbv_ratio?: number;
  market_cap?: string | number;
  roe?: number;
  roa?: number;
  dividend_yield?: number;
  eps?: number;
  revenue?: string;
  net_income?: string;
  piotroski_f_score?: number;
  npm?: number;
  free_float?: string;
  shares_outstanding?: string;
}
