import {
  HealthState,
  Quote,
  Book,
  Candle,
  Trade,
  MoverItem,
  BrokerItem,
  BrokerSummary,
  BrokerFlowEntry,
  SectorItem,
  SubsectorItem,
  SectorCompany,
  KeyStats,
  CompanyProfile,
} from '../types/datafeed';

const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8000';

export function getStoredBackendUrl(): string {
  if (typeof window !== 'undefined' && window.localStorage) {
    const saved = localStorage.getItem('axiom_backend_url');
    if (saved) return saved;
  }
  return DEFAULT_BACKEND_URL;
}

export function setStoredBackendUrl(url: string): void {
  if (typeof window !== 'undefined' && window.localStorage) {
    localStorage.setItem('axiom_backend_url', url.replace(/\/$/, ''));
  }
}

export function getStoredApiKey(): string {
  if (typeof window !== 'undefined' && window.localStorage) {
    return localStorage.getItem('axiom_api_key') || '';
  }
  return '';
}

export function setStoredApiKey(key: string): void {
  if (typeof window !== 'undefined' && window.localStorage) {
    localStorage.setItem('axiom_api_key', key.trim());
  }
}

function getUrlCandidates(targetUrl: string): string[] {
  const clean = targetUrl.replace(/\/$/, '');
  const list = [clean];

  if (clean.includes('localhost')) {
    list.push(clean.replace('localhost', '127.0.0.1'));
  } else if (clean.includes('127.0.0.1')) {
    list.push(clean.replace('127.0.0.1', 'localhost'));
  }

  if (clean.includes('8000') || clean.includes('localhost') || clean.includes('127.0.0.1')) {
    list.push(''); // relative proxy
  }

  return Array.from(new Set(list));
}

function buildHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const apiKey = getStoredApiKey();
  if (apiKey) headers['X-API-Key'] = apiKey;
  return headers;
}

export async function checkBackendHealth(baseUrl: string = getStoredBackendUrl()): Promise<{
  isLive: boolean;
  data?: HealthState;
  error?: string;
  connectedUrl?: string;
}> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();
  let lastError = 'Unable to connect to backend';

  for (const base of candidates) {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);
      const res = await fetch(`${base}/v1/health`, { headers, signal: controller.signal });
      clearTimeout(timeoutId);

      if (res.ok) {
        const data = await res.json();
        return { isLive: true, data, connectedUrl: base || 'Vite Proxy' };
      }
    } catch (e: any) {
      lastError = e.message || 'Connection failed';
    }
  }

  return { isLive: false, error: lastError };
}

export async function fetchLiveTrades(
  symbol: string,
  limit: number = 50,
  baseUrl: string = getStoredBackendUrl()
): Promise<Trade[]> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/trades?symbols=${symbol.toUpperCase()}&limit=${limit}`, { headers });
      if (res.ok) {
        const data = await res.json();
        const raw = Array.isArray(data) ? data : data.trades || [];
        return raw.map((t: any, i: number) => ({
          symbol: t.symbol || symbol.toUpperCase(),
          price: (t.price ?? '0').toString(),
          volume: Number(t.volume || t.lots || 0),
          side: (t.side || 'BUY').toUpperCase() as any,
          board: (t.board || 'RG').toUpperCase() as any,
          ts: t.ts || t.time || '',
          seq: Number(t.seq || i + 1),
          change: t.change?.toString(),
          change_pct: t.change_pct?.toString(),
        }));
      }
    } catch {}
  }

  return [];
}

export async function fetchLiveQuote(symbol: string, baseUrl: string = getStoredBackendUrl()): Promise<Quote | null> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();
  const sym = symbol.toUpperCase();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/quotes/${sym}`, { headers });
      if (res.ok) {
        const data = await res.json();
        const q = data.quote;
        if (q) {
          let changeStr = q.change;
          let changePctStr = q.change_pct;
          if (!changeStr && q.last && q.prev_close) {
            const diff = parseFloat(q.last) - parseFloat(q.prev_close);
            changeStr = diff > 0 ? `+${diff.toFixed(2)}` : diff.toFixed(2);
            changePctStr = ((diff / parseFloat(q.prev_close)) * 100).toFixed(2) + '%';
          }

          return {
            symbol: data.symbol || sym,
            last: (q.last ?? '').toString(),
            open: q.open?.toString() || undefined,
            high: q.high?.toString() || undefined,
            low: q.low?.toString() || undefined,
            prev_close: q.prev_close?.toString() || undefined,
            change: changeStr,
            change_pct: changePctStr,
            volume: q.volume ? Number(q.volume) : undefined,
            value: q.value?.toString() || undefined,
            freq: q.freq ? Number(q.freq) : undefined,
            avg: q.avg?.toString() || undefined,
            ts: q.ts || new Date().toISOString(),
            is_index: sym === 'IHSG',
          };
        }
      }
    } catch {}

    try {
      const res = await fetch(`${base}/v1/companies/${sym}`, { headers });
      if (res.ok) {
        const data = await res.json();
        const d = data.data || {};
        return {
          symbol: sym,
          last: (d.last || d.price || d.average || '0').toString(),
          change: d.change?.toString(),
          change_pct: d.change_pct?.toString(),
          volume: d.volume ? Number(d.volume) : undefined,
          avg: d.average?.toString(),
          ts: d.date || new Date().toISOString(),
          is_index: sym === 'IHSG',
        };
      }
    } catch {}
  }
  return null;
}

export async function fetchLiveBook(symbol: string, baseUrl: string = getStoredBackendUrl()): Promise<Book | null> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();
  const sym = symbol.toUpperCase();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/books/${sym}`, { headers });
      if (res.ok) {
        const data = await res.json();
        if (data.book && (data.book.bids?.length > 0 || data.book.asks?.length > 0)) {
          return {
            symbol: data.symbol || sym,
            bids: (data.book.bids || []).map((b: any) => ({
              price: b.price?.toString() || '0',
              lots: Number(b.lots || 0),
            })),
            asks: (data.book.asks || []).map((a: any) => ({
              price: a.price?.toString() || '0',
              lots: Number(a.lots || 0),
            })),
            ts: data.book.ts || new Date().toISOString(),
            seq: 1,
          };
        }
      }
    } catch {}

    try {
      const res = await fetch(`${base}/v1/books/snapshot/${sym}`, { headers });
      if (res.ok) {
        const data = await res.json();
        const snap = data.snapshot?.data?.tradebook || data.snapshot?.data || {};
        const bids: any[] = [];
        const asks: any[] = [];

        if (Array.isArray(snap.bid)) {
          snap.bid.forEach((b: any) => {
            if (b.price || b.p) {
              bids.push({ price: (b.price || b.p).toString(), lots: Number(b.lot || b.lots || b.volume || 0) });
            }
          });
        }
        if (Array.isArray(snap.offer || snap.ask)) {
          (snap.offer || snap.ask).forEach((a: any) => {
            if (a.price || a.p) {
              asks.push({ price: (a.price || a.p).toString(), lots: Number(a.lot || a.lots || a.volume || 0) });
            }
          });
        }

        if (bids.length > 0 || asks.length > 0) {
          return {
            symbol: sym,
            bids,
            asks,
            ts: new Date().toISOString(),
            seq: 1,
          };
        }
      }
    } catch {}
  }
  return null;
}

export async function fetchLiveCandles(
  symbol: string,
  from: string,
  to: string,
  resolution: 'daily' | 'minute',
  baseUrl: string = getStoredBackendUrl()
): Promise<Candle[]> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();
  const sym = symbol.toUpperCase();

  for (const base of candidates) {
    try {
      const res = await fetch(
        `${base}/v1/candles/${sym}?from=${from}&to=${to}&resolution=${resolution}`,
        { headers }
      );
      if (res.ok) {
        const text = await res.text();
        const lines = text.split('\n').filter((l) => l.trim());
        const candles: Candle[] = [];
        for (const line of lines) {
          try {
            const item = JSON.parse(line);
            if (item.ts && item.close !== undefined) {
              candles.push({
                ts: item.ts,
                open: item.open?.toString() || '0',
                high: item.high?.toString() || '0',
                low: item.low?.toString() || '0',
                close: item.close?.toString() || '0',
                volume: Number(item.volume || 0),
                value: item.value?.toString() || '0',
                freq: item.freq ? Number(item.freq) : undefined,
              });
            }
          } catch {}
        }
        if (candles.length > 0) return candles;
      }
    } catch {}
  }
  return [];
}

export async function fetchPricePerformance(symbol: string, baseUrl: string = getStoredBackendUrl()): Promise<any[]> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/charts/${symbol.toUpperCase()}/performance`, { headers });
      if (res.ok) {
        const data = await res.json();
        return data.performance?.prices || [];
      }
    } catch {}
  }
  return [];
}

export async function fetchMarketMovers(
  kind: string = 'top_gainers',
  baseUrl: string = getStoredBackendUrl()
): Promise<MoverItem[]> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/market/movers?kind=${kind}`, { headers });
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data.movers) ? data.movers : [];
        return list.map((m: any) => {
          let pctStr = (m.change_pct ?? '').toString().replace('%', '');
          return {
            symbol: m.symbol || '—',
            last: (m.last ?? '0').toString(),
            change: (m.change ?? '0').toString(),
            change_pct: pctStr,
            volume: typeof m.volume === 'object' ? m.volume?.raw : m.volume,
            value: typeof m.value === 'object' ? m.value?.raw : m.value,
            name: m.name,
          };
        });
      }
    } catch {}
  }
  return [];
}

export async function fetchBrokersTop(baseUrl: string = getStoredBackendUrl()): Promise<BrokerItem[]> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/brokers/top`, { headers });
      if (res.ok) {
        const data = await res.json();
        const list = data.brokers?.data?.list || [];
        if (Array.isArray(list) && list.length > 0) {
          return list.map((b: any) => {
            const buyVal = parseFloat(b.buy_value || b.buy_val || 0);
            const sellVal = parseFloat(b.sell_value || b.sell_val || 0);
            const netVal = parseFloat(b.net_value || b.net_val || (buyVal - sellVal));
            const isForeign = (b.group || '').toUpperCase().includes('FOREIGN') || (b.code || '').startsWith('F');

            return {
              code: b.code || '—',
              name: b.name || b.code || 'Broker',
              type: isForeign ? 'F' : 'D',
              buy_val: buyVal,
              sell_val: sellVal,
              net_val: netVal,
              buy_vol: Number(b.total_volume || b.buy_vol || 0),
              sell_vol: Number(b.sell_vol || 0),
              top_stock: b.top_stock || '—',
            };
          });
        }
      }
    } catch {}
  }
  return [];
}

export async function fetchBrokerSummary(
  symbol: string,
  baseUrl: string = getStoredBackendUrl()
): Promise<BrokerSummary | null> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();
  const sym = symbol.toUpperCase();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/brokers/summary/${sym}`, { headers });
      if (res.ok) {
        const data = await res.json();
        const bdData = data.data?.data || {};
        const detector = bdData.bandar_detector || {};
        const avg = detector.avg || {};
        const summary = bdData.broker_summary || {};
        const brokersBuy = summary.brokers_buy || [];
        const brokersSell = summary.brokers_sell || [];

        const mapEntries = (list: any[]): BrokerFlowEntry[] =>
          list.map((it: any) => ({
            broker_code: it.netbs_broker_code || it.broker_code || '—',
            stock_code: it.netbs_stock_code || it.stock || sym,
            avg_price: parseFloat(it.netbs_buy_avg_price || it.netbs_sell_avg_price || it.average || 0),
            lots: Math.abs(parseInt(it.blot || it.slot || it.lot || 0, 10)),
            value: Math.abs(parseFloat(it.bval || it.sval || it.val || 0)),
            type: it.type || '',
            freq: parseInt(it.freq || 0, 10),
          }));

        return {
          symbol: sym,
          status: avg.accdist || detector.broker_accdist || 'Neutral',
          avg_price: Number(detector.average || 0),
          broker_accdist: detector.broker_accdist,
          top_buyers: mapEntries(brokersBuy),
          top_sellers: mapEntries(brokersSell),
        };
      }
    } catch {}
  }
  return null;
}

export async function fetchBrokerTopStocks(baseUrl: string = getStoredBackendUrl()): Promise<any> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/brokers/top-stocks`, { headers });
      if (res.ok) {
        const data = await res.json();
        const topBuy = data.stocks?.data?.top_buy || [];
        const topSell = data.stocks?.data?.top_sell || [];
        return { top_buy: topBuy, top_sell: topSell };
      }
    } catch {}
  }
  return { top_buy: [], top_sell: [] };
}

export async function fetchBrokerActivity(
  brokerCode: string,
  baseUrl: string = getStoredBackendUrl()
): Promise<any> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/brokers/${brokerCode.toUpperCase()}/activity`, { headers });
      if (res.ok) {
        const data = await res.json();
        const adata = data.activity?.data || {};
        const summary = adata.broker_summary || {};
        return {
          broker: brokerCode.toUpperCase(),
          detector: adata.bandar_detector,
          buys: (summary.brokers_buy || []).map((it: any) => ({
            stock: it.netbs_stock_code,
            lots: parseInt(it.blot || 0, 10),
            value: parseFloat(it.bval || 0),
            avg_price: parseFloat(it.netbs_buy_avg_price || 0),
          })),
          sells: (summary.brokers_sell || []).map((it: any) => ({
            stock: it.netbs_stock_code,
            lots: Math.abs(parseInt(it.slot || 0, 10)),
            value: Math.abs(parseFloat(it.sval || 0)),
            avg_price: parseFloat(it.netbs_sell_avg_price || 0),
          })),
        };
      }
    } catch {}
  }
  return null;
}

export async function fetchSectors(baseUrl: string = getStoredBackendUrl()): Promise<SectorItem[]> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/sectors`, { headers });
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data.sectors) ? data.sectors : [];
        return list.map((s: any) => ({
          id: (s.id || s.alias1 || s.name).toString(),
          name: s.name || 'Sector',
          alias: s.alias1,
          change_pct: s.change_pct ? parseFloat(s.change_pct) : undefined,
          companies_count: s.companies_count ? Number(s.companies_count) : undefined,
        }));
      }
    } catch {}
  }
  return [];
}

export async function fetchSubsectors(
  sectorId: string,
  baseUrl: string = getStoredBackendUrl()
): Promise<SubsectorItem[]> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/sectors/${sectorId}/subsectors`, { headers });
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data.subsectors) ? data.subsectors : [];
        return list.map((sub: any) => ({
          id: (sub.id || sub.name).toString(),
          name: sub.name || 'Subsector',
          companies_count: sub.count ? Number(sub.count) : undefined,
        }));
      }
    } catch {}
  }
  return [];
}

export async function fetchSectorCompanies(
  sectorId: string,
  subsectorId: string,
  baseUrl: string = getStoredBackendUrl()
): Promise<SectorCompany[]> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/sectors/${sectorId}/subsectors/${subsectorId}/companies`, { headers });
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data.companies) ? data.companies : [];
        return list.map((c: any) => ({
          symbol: c.symbol || c.stock || '—',
          name: c.name || c.symbol || 'Company',
          last: (c.last || c.price || '0').toString(),
          change: (c.change || '0').toString(),
          change_pct: (c.change_pct || '0').toString().replace('%', ''),
          market_cap: c.market_cap?.toString(),
          volume: c.volume ? Number(c.volume) : undefined,
        }));
      }
    } catch {}
  }
  return [];
}

export async function fetchFundamentals(
  symbol: string,
  baseUrl: string = getStoredBackendUrl()
): Promise<KeyStats | null> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();
  const sym = symbol.toUpperCase();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/fundamentals/${sym}`, { headers });
      if (res.ok) {
        const data = await res.json();
        const ksData = data.key_stats?.data || {};
        const stats = ksData.stats || {};
        const groups = ksData.closure_fin_items_results || [];

        const fitems: Record<string, string> = {};
        for (const g of groups) {
          for (const r of g.fin_name_results || []) {
            if (r.fitem?.name && r.fitem?.value !== undefined) {
              fitems[r.fitem.name.trim()] = r.fitem.value;
            }
          }
        }

        const parseNum = (val: string | undefined): number | undefined => {
          if (!val || val === '-' || val === 'null') return undefined;
          const clean = val.replace(/,/g, '').replace(/%/g, '').trim();
          const n = parseFloat(clean);
          return isNaN(n) ? undefined : n;
        };

        return {
          symbol: sym,
          pe_ratio: parseNum(fitems['Current PE Ratio (TTM)'] || fitems['Current PE Ratio (Annualised)']),
          pe_ttm: parseNum(fitems['Current PE Ratio (TTM)']),
          pbv_ratio: parseNum(fitems['Current Price to Book Value']),
          market_cap: stats.market_cap || fitems['Market Cap'],
          roe: parseNum(fitems['Return on Equity (TTM)']),
          roa: parseNum(fitems['Return on Assets (TTM)']),
          dividend_yield: parseNum(fitems['Dividend Yield']),
          eps: parseNum(fitems['Current EPS (TTM)'] || fitems['Current EPS (Annualised)']),
          revenue: fitems['Revenue (TTM)'],
          net_income: fitems['Net Income (TTM)'],
          piotroski_f_score: parseNum(fitems['Piotroski F-Score']),
          npm: parseNum(fitems['Net Profit Margin (Quarter)']),
          free_float: stats.free_float,
          shares_outstanding: stats.current_share_outstanding,
        };
      }
    } catch {}
  }
  return null;
}

export async function fetchFinancials(
  symbol: string,
  reportType: number = 1,
  statementType: number = 1,
  baseUrl: string = getStoredBackendUrl()
): Promise<any | null> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(
        `${base}/v1/fundamentals/${symbol.toUpperCase()}/financials?data_type=1&report_type=${reportType}&statement_type=${statementType}`,
        { headers }
      );
      if (res.ok) {
        return await res.json();
      }
    } catch {}
  }
  return null;
}

export async function fetchCompanyProfile(
  symbol: string,
  baseUrl: string = getStoredBackendUrl()
): Promise<CompanyProfile | null> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();
  const sym = symbol.toUpperCase();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/companies/${sym}/profile`, { headers });
      if (res.ok) {
        const data = await res.json();
        const profile = data.profile || {};
        const address = Array.isArray(profile.address) && profile.address[0] ? profile.address[0] : {};

        return {
          symbol: sym,
          name: profile.name || sym,
          sector: profile.sector || profile.industry,
          subsector: profile.sub_sector,
          address: address.address,
          email: Array.isArray(address.email) ? address.email[0] : address.email,
          phone: Array.isArray(address.phone) ? address.phone[0] : address.phone,
          website: address.website,
          listing_date: profile.listing_date,
          description: profile.description,
        };
      }
    } catch {}
  }
  return null;
}

export async function fetchCompanySubsidiaries(
  symbol: string,
  baseUrl: string = getStoredBackendUrl()
): Promise<any[]> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/companies/${symbol.toUpperCase()}/subsidiaries`, { headers });
      if (res.ok) {
        const data = await res.json();
        return data.subsidiaries || [];
      }
    } catch {}
  }
  return [];
}

export async function fetchCalendars(
  type: string = 'dividend',
  baseUrl: string = getStoredBackendUrl()
): Promise<any> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/calendars/${type}`, { headers });
      if (res.ok) {
        const data = await res.json();
        return data.data || null;
      }
    } catch {}
  }
  return null;
}

export async function fetchCompanyActions(
  symbol: string,
  baseUrl: string = getStoredBackendUrl()
): Promise<any[]> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/calendars/companies/${symbol.toUpperCase()}/actions?limit=30`, { headers });
      if (res.ok) {
        const data = await res.json();
        return data.actions || [];
      }
    } catch {}
  }
  return [];
}

export async function fetchSeasonality(
  symbol: string,
  year: number = 2026,
  backYear: number = 5,
  baseUrl: string = getStoredBackendUrl()
): Promise<any> {
  const candidates = getUrlCandidates(baseUrl);
  const headers = buildHeaders();

  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/v1/seasonality/${symbol.toUpperCase()}?year=${year}&back_year=${backYear}`, {
        headers,
      });
      if (res.ok) {
        const data = await res.json();
        return data.data?.data || null;
      }
    } catch {}
  }
  return null;
}

export function createLiveWebSocket(
  onMessage: (msg: any) => void,
  onOpen?: () => void,
  onClose?: () => void,
  onError?: (err: any) => void,
  baseUrl: string = getStoredBackendUrl()
): { close: () => void; send: (data: string) => void; isConnected: () => boolean } {
  const apiKey = getStoredApiKey();
  let host = baseUrl.replace(/^https?:\/\//, '').replace(/\/$/, '');
  if (host.includes('localhost')) host = host.replace('localhost', '127.0.0.1');
  if (!host) host = '127.0.0.1:8000';

  const wsProto = baseUrl.startsWith('https') ? 'wss:' : 'ws:';
  let activeWs: WebSocket | null = null;
  let isClosedExplicitly = false;

  const connect = () => {
    if (isClosedExplicitly) return;

    const wsUrl = `${wsProto}//${host}/v1/stream${apiKey ? `?token=${encodeURIComponent(apiKey)}` : ''}`;
    try {
      const ws = new WebSocket(wsUrl);
      activeWs = ws;

      ws.onopen = () => {
        onOpen?.();
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          onMessage(data);
        } catch {
          onMessage({ raw: event.data });
        }
      };

      ws.onerror = (e) => {
        onError?.(e);
      };

      ws.onclose = () => {
        if (!isClosedExplicitly) {
          onClose?.();
        }
      };
    } catch (err) {
      onError?.(err);
    }
  };

  connect();

  return {
    close: () => {
      isClosedExplicitly = true;
      activeWs?.close();
    },
    send: (data: string) => {
      if (activeWs && activeWs.readyState === WebSocket.OPEN) {
        activeWs.send(data);
      }
    },
    isConnected: () => activeWs?.readyState === WebSocket.OPEN,
  };
}
