import React, { useState, useEffect } from 'react';
import { fetchCalendars, fetchCompanyActions, getStoredBackendUrl } from '../services/api';
import { ApiSpecDrawer } from './ApiSpecDrawer';

interface CalendarsViewProps {
  selectedSymbol: string;
}

export const CalendarsView: React.FC<CalendarsViewProps> = ({ selectedSymbol }) => {
  const [calendarType, setCalendarType] = useState<string>('dividend');
  const [calendarData, setCalendarData] = useState<any>(null);
  const [companyActions, setCompanyActions] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    const loadData = async () => {
      const [cal, act] = await Promise.all([
        fetchCalendars(calendarType, getStoredBackendUrl()),
        fetchCompanyActions(selectedSymbol, getStoredBackendUrl()),
      ]);
      if (mounted) {
        if (cal) setCalendarData(cal);
        if (act) setCompanyActions(act);
        setLoading(false);
      }
    };

    loadData();
    return () => {
      mounted = false;
    };
  }, [calendarType, selectedSymbol]);

  const calendarTypes = [
    { id: 'dividend', label: 'Dividends' },
    { id: 'ipo', label: 'IPO Filings' },
    { id: 'economic', label: 'Economic Releases' },
    { id: 'tenderoffer', label: 'Tender Offers' },
    { id: 'rightissue', label: 'Rights Issues' },
    { id: 'stocksplit', label: 'Stock Splits' },
  ];

  const renderCalendarList = () => {
    if (!calendarData) return <div className="p-8 text-center text-[#7e7e7e]">No calendar records found.</div>;

    // 1. Dividend Table
    if (calendarType === 'dividend' && Array.isArray(calendarData.dividend)) {
      return (
        <table className="w-full text-left font-mono text-[12px]">
          <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
            <tr>
              <th className="py-2 px-3 font-normal">SYMBOL</th>
              <th className="py-2 px-3 font-normal text-right">DIVIDEND (RP)</th>
              <th className="py-2 px-3 font-normal">CUM-DATE</th>
              <th className="py-2 px-3 font-normal">EX-DATE</th>
              <th className="py-2 px-3 font-normal">PAY-DATE</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
            {calendarData.dividend.slice(0, 50).map((d: any, idx: number) => (
              <tr key={idx} className="hover:bg-[#191919] transition-colors">
                <td className="py-2 px-3 font-bold text-[#eeeeee]">{d.company_symbol}</td>
                <td className="py-2 px-3 text-right text-[#da5c2c] font-bold">
                  Rp {d.dividend_value || '—'}
                </td>
                <td className="py-2 px-3 text-[#b4b4b4]">{d.dividend_cumdate || '—'}</td>
                <td className="py-2 px-3 text-[#b4b4b4]">{d.dividend_exdate || '—'}</td>
                <td className="py-2 px-3 text-[#7e7e7e]">{d.dividend_paydate || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    }

    // 2. IPO Table
    if (calendarType === 'ipo' && Array.isArray(calendarData.ipo)) {
      return (
        <table className="w-full text-left font-mono text-[12px]">
          <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
            <tr>
              <th className="py-2.5 px-3 font-normal">SYMBOL</th>
              <th className="py-2.5 px-3 font-normal">COMPANY NAME</th>
              <th className="py-2.5 px-3 font-normal">LISTING DATE</th>
              <th className="py-2.5 px-3 font-normal">OFFERING DETAILS</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
            {calendarData.ipo.map((ipo: any, idx: number) => {
              let parsed: any = {};
              try {
                parsed = JSON.parse(ipo.ipo_data);
              } catch {}
              return (
                <tr key={idx} className="hover:bg-[#191919] transition-colors">
                  <td className="py-2.5 px-3 font-bold text-[#eeeeee]">{ipo.company_symbol}</td>
                  <td className="py-2.5 px-3 text-[#b4b4b4]">{ipo.company_name}</td>
                  <td className="py-2.5 px-3 text-[#7e7e7e]">{ipo.ipo_listing_date}</td>
                  <td className="py-2.5 px-3 text-[#da5c2c]">
                    Price: Rp {parsed.Price || '—'} · Shares: {parsed.Shares || '—'} ({parsed['%'] || ''}%)
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      );
    }

    // 3. Economic Releases Table
    if (calendarType === 'economic' && Array.isArray(calendarData.economic)) {
      return (
        <table className="w-full text-left font-mono text-[12px]">
          <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
            <tr>
              <th className="py-2.5 px-3 font-normal">DATE / TIME</th>
              <th className="py-2.5 px-3 font-normal">MACROECONOMIC EVENT</th>
              <th className="py-2.5 px-3 font-normal text-right">ACTUAL</th>
              <th className="py-2.5 px-3 font-normal text-right">PREVIOUS</th>
              <th className="py-2.5 px-3 font-normal text-right">FORECAST</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
            {calendarData.economic.map((e: any, idx: number) => (
              <tr key={idx} className="hover:bg-[#191919] transition-colors">
                <td className="py-2 px-3 text-[#7e7e7e]">{e.econcal_date} {e.econcal_time || ''}</td>
                <td className="py-2 px-3 font-bold text-[#eeeeee]">{e.econcal_item} ({e.econcal_month || ''})</td>
                <td className="py-2 px-3 text-right font-bold text-[#da5c2c]">{e.econcal_actual || '—'}</td>
                <td className="py-2 px-3 text-right text-[#b4b4b4]">{e.econcal_previous || '—'}</td>
                <td className="py-2 px-3 text-right text-[#7e7e7e]">{e.econcal_forecast || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    }

    // 4. Tender Offers Table
    if ((calendarType === 'tenderoffer' || calendarType === 'tender') && Array.isArray(calendarData.tender || calendarData)) {
      const list = Array.isArray(calendarData.tender) ? calendarData.tender : calendarData;
      return (
        <table className="w-full text-left font-mono text-[12px]">
          <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
            <tr>
              <th className="py-2.5 px-3 font-normal">SYMBOL</th>
              <th className="py-2.5 px-3 font-normal">COMPANY NAME</th>
              <th className="py-2.5 px-3 font-normal text-right">TENDER PRICE</th>
              <th className="py-2.5 px-3 font-normal">START DATE</th>
              <th className="py-2.5 px-3 font-normal">END DATE</th>
              <th className="py-2.5 px-3 font-normal">PAYMENT DATE</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
            {list.map((t: any, idx: number) => (
              <tr key={idx} className="hover:bg-[#191919] transition-colors">
                <td className="py-2 px-3 font-bold text-[#eeeeee]">{t.company_symbol}</td>
                <td className="py-2 px-3 text-[#b4b4b4]">{t.company_name}</td>
                <td className="py-2 px-3 text-right font-bold text-[#da5c2c]">Rp {t.tender_price ? parseInt(t.tender_price).toLocaleString() : '—'}</td>
                <td className="py-2 px-3 text-[#7e7e7e]">{t.tender_start || '—'}</td>
                <td className="py-2 px-3 text-[#b4b4b4]">{t.tender_end || '—'}</td>
                <td className="py-2 px-3 text-[#7e7e7e]">{t.tender_paydate || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    }

    // 5. Rights Issues Table
    if (calendarType === 'rightissue' && Array.isArray(calendarData.rightissue || calendarData)) {
      const list = Array.isArray(calendarData.rightissue) ? calendarData.rightissue : calendarData;
      return (
        <table className="w-full text-left font-mono text-[12px]">
          <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
            <tr>
              <th className="py-2.5 px-3 font-normal">SYMBOL</th>
              <th className="py-2.5 px-3 font-normal text-right">PRICE (RP)</th>
              <th className="py-2.5 px-3 font-normal">RATIO</th>
              <th className="py-2.5 px-3 font-normal">CUM-DATE</th>
              <th className="py-2.5 px-3 font-normal">EX-DATE</th>
              <th className="py-2.5 px-3 font-normal">TRADING PERIOD</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
            {list.map((r: any, idx: number) => (
              <tr key={idx} className="hover:bg-[#191919] transition-colors">
                <td className="py-2 px-3 font-bold text-[#eeeeee]">{r.company_symbol}</td>
                <td className="py-2 px-3 text-right font-bold text-[#da5c2c]">Rp {r.rightissue_price || '—'}</td>
                <td className="py-2 px-3 text-[#b4b4b4]">{r.rightissue_ratio || `${r.rightissue_old} : ${r.rightissue_new}`}</td>
                <td className="py-2 px-3 text-[#7e7e7e]">{r.rightissue_cumdate || '—'}</td>
                <td className="py-2 px-3 text-[#7e7e7e]">{r.rightissue_exdate || '—'}</td>
                <td className="py-2 px-3 text-[#7e7e7e]">{r.rightissue_trading_start || '—'} → {r.rightissue_trading_end || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    }

    // 6. Stock Splits Table
    if (calendarType === 'stocksplit' && Array.isArray(calendarData.stocksplit || calendarData)) {
      const list = Array.isArray(calendarData.stocksplit) ? calendarData.stocksplit : calendarData;
      return (
        <table className="w-full text-left font-mono text-[12px]">
          <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
            <tr>
              <th className="py-2.5 px-3 font-normal">SYMBOL</th>
              <th className="py-2.5 px-3 font-normal">SPLIT RATIO</th>
              <th className="py-2.5 px-3 font-normal text-right">OLD NOMINAL</th>
              <th className="py-2.5 px-3 font-normal text-right">NEW NOMINAL</th>
              <th className="py-2.5 px-3 font-normal">SPLIT DATE</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
            {list.map((s: any, idx: number) => (
              <tr key={idx} className="hover:bg-[#191919] transition-colors">
                <td className="py-2 px-3 font-bold text-[#eeeeee]">{s.company_symbol}</td>
                <td className="py-2 px-3 font-bold text-[#da5c2c]">{s.stocksplit_ratio || `${s.stocksplit_old} : ${s.stocksplit_new}`}</td>
                <td className="py-2 px-3 text-right text-[#b4b4b4]">Rp {s.stocksplit_old || '—'}</td>
                <td className="py-2 px-3 text-right text-[#eeeeee]">Rp {s.stocksplit_new || '—'}</td>
                <td className="py-2 px-3 text-[#7e7e7e]">{s.stocksplit_date || s.stocksplit_cumdate || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      );
    }

    return (
      <pre className="p-4 text-[#b4b4b4] text-[11px] overflow-x-auto max-h-96">
        {JSON.stringify(calendarData, null, 2)}
      </pre>
    );
  };

  return (
    <div className="space-y-4 font-mono text-[13px]">
      <ApiSpecDrawer
        method="GET"
        endpoint="/v1/calendars/:type"
        queryParams={`/v1/calendars/companies/${selectedSymbol}/actions`}
        useCaseTitle="Corporate Actions & Earnings Event Calendars"
        useCaseDescription="Tracks upcoming IPO offerings, dividend ex-dates, macroeconomic release dates, tender offers, rights issues, and stock split schedules across the entire IDX exchange."
        curlCommand={`curl -s "http://127.0.0.1:8000/v1/calendars/${calendarType}"`}
        responsePreview={`{
  "type": "${calendarType}",
  "data": { ... }
}`}
      />

      {/* Selected Company Actions Banner */}
      {companyActions.length > 0 && (
        <div className="border border-[#202020] bg-[#111111] p-4 rounded-[2px] space-y-2">
          <div className="flex items-center justify-between border-b border-[#202020] pb-2 text-[#b4b4b4] text-[12px] font-bold">
            <span>HISTORICAL CORPORATE ACTIONS · {selectedSymbol}</span>
            <code className="text-[#7e7e7e] text-[11px]">GET /v1/calendars/companies/{selectedSymbol}/actions</code>
          </div>
          <div className="space-y-1.5 text-[12px]">
            {companyActions.slice(0, 5).map((act: any, idx: number) => {
              const div = act.action_info?.dividend || {};
              return (
                <div key={idx} className="flex justify-between py-1 border-b border-[#191919]">
                  <span className="text-[#eeeeee] font-bold uppercase">{act.action_type}</span>
                  <span className="text-[#da5c2c] font-bold">
                    {div.dividend_value ? `Rp ${div.dividend_value}` : '—'}
                  </span>
                  <span className="text-[#7e7e7e]">Ex-Date: {div.dividend_exdate || '—'}</span>
                  <span className="text-[#7e7e7e]">Pay-Date: {div.dividend_paydate || '—'}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Calendar Category Switcher */}
      <div className="flex flex-wrap items-center gap-2 p-3 bg-[#000000] border border-[#202020] rounded-[2px]">
        <span className="text-[#7e7e7e] text-[12px]">Calendar:</span>
        {calendarTypes.map((t) => (
          <button
            key={t.id}
            onClick={() => setCalendarType(t.id)}
            className={`btn-action-sm ${calendarType === t.id ? 'active' : ''}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Main Calendar View Table */}
      <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-[#7e7e7e]">Loading {calendarType} calendar data...</div>
        ) : (
          renderCalendarList()
        )}
      </div>
    </div>
  );
};
