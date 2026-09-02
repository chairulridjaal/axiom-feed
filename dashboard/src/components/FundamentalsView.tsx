import React, { useState, useEffect } from 'react';
import { fetchFundamentals, fetchCompanyProfile, fetchCompanySubsidiaries, fetchFinancials, getStoredBackendUrl } from '../services/api';
import { KeyStats, CompanyProfile } from '../types/datafeed';
import { ApiSpecDrawer } from './ApiSpecDrawer';

interface FundamentalsViewProps {
  selectedSymbol: string;
}

export const FundamentalsView: React.FC<FundamentalsViewProps> = ({ selectedSymbol }) => {
  const [stats, setStats] = useState<KeyStats | null>(null);
  const [profile, setProfile] = useState<CompanyProfile | null>(null);
  const [subsidiaries, setSubsidiaries] = useState<any[]>([]);
  const [financials, setFinancials] = useState<any | null>(null);
  const [reportType, setReportType] = useState<number>(1); // 1: Income Statement, 2: Balance Sheet, 3: Cash Flow
  const [statementType, setStatementType] = useState<number>(1); // 1: Quarterly, 2: Annually, 3: TTM
  const [activeSubTab, setActiveSubTab] = useState<'valuation' | 'statements' | 'subsidiaries'>('valuation');
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);

    const loadData = async () => {
      const [fundData, profData, subData, finData] = await Promise.all([
        fetchFundamentals(selectedSymbol, getStoredBackendUrl()),
        fetchCompanyProfile(selectedSymbol, getStoredBackendUrl()),
        fetchCompanySubsidiaries(selectedSymbol, getStoredBackendUrl()),
        fetchFinancials(selectedSymbol, reportType, statementType, getStoredBackendUrl()),
      ]);
      if (mounted) {
        if (fundData) setStats(fundData);
        if (profData) setProfile(profData);
        if (subData) setSubsidiaries(subData);
        if (finData) setFinancials(finData);
        setLoading(false);
      }
    };

    loadData();
    return () => {
      mounted = false;
    };
  }, [selectedSymbol, reportType, statementType]);

  const periods: string[] = financials?.periods || [];
  const lineItems: any[] = financials?.line_items || [];
  const recentPeriods = periods.slice(-8); // Show latest 8 periods

  return (
    <div className="space-y-4 font-mono text-[13px]">
      <ApiSpecDrawer
        method="GET"
        endpoint="/v1/fundamentals/:symbol"
        queryParams={`/v1/fundamentals/${selectedSymbol}/financials?report_type=${reportType}&statement_type=${statementType} · /v1/companies/${selectedSymbol}/subsidiaries`}
        useCaseTitle="Fundamental Valuation, Financial Statements & Subsidiaries"
        useCaseDescription="Extracts corporate valuation ratios, parsed financial statement lines (Income Statement, Balance Sheet, Cash Flow across quarterly/annual periods), and corporate subsidiary ownership breakdowns."
        curlCommand={`curl -s "http://127.0.0.1:8000/v1/fundamentals/${selectedSymbol}/financials?report_type=${reportType}&statement_type=${statementType}"`}
        responsePreview={`{
  "symbol": "${selectedSymbol}",
  "unit": "${financials?.unit || 'In Million'}",
  "periods": ${JSON.stringify(recentPeriods.slice(-4))},
  "line_items": [ { "name": "Total Pendapatan", "values": [...] } ]
}`}
      />

      {/* Sub-Tab Navigation Bar */}
      <div className="flex items-center gap-2 p-3 bg-[#000000] border border-[#202020] rounded-[2px]">
        <button
          onClick={() => setActiveSubTab('valuation')}
          className={`btn-action-sm ${activeSubTab === 'valuation' ? 'active' : ''}`}
        >
          Valuation & Profile
        </button>
        <button
          onClick={() => setActiveSubTab('statements')}
          className={`btn-action-sm ${activeSubTab === 'statements' ? 'active' : ''}`}
        >
          Structured Financial Statements
        </button>
        <button
          onClick={() => setActiveSubTab('subsidiaries')}
          className={`btn-action-sm ${activeSubTab === 'subsidiaries' ? 'active' : ''}`}
        >
          Subsidiaries ({subsidiaries.length})
        </button>
      </div>

      {loading && !stats ? (
        <div className="border border-[#202020] bg-[#111111] p-8 text-center text-[#7e7e7e]">
          Loading fundamental data for {selectedSymbol}...
        </div>
      ) : (
        <>
          {activeSubTab === 'valuation' && (
            <div className="space-y-4">
              {/* 6 Key Stat Cards */}
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
                <div className="border border-[#202020] bg-[#111111] p-3.5 rounded-[2px]">
                  <div className="text-[#7e7e7e] text-[11px] mb-1">P/E RATIO (TTM)</div>
                  <div className="text-[#eeeeee] font-bold text-[16px]">
                    {stats?.pe_ratio !== undefined ? `${stats.pe_ratio}×` : '—'}
                  </div>
                  <div className="text-[#7e7e7e] text-[11px] mt-0.5">Price / Earnings</div>
                </div>

                <div className="border border-[#202020] bg-[#111111] p-3.5 rounded-[2px]">
                  <div className="text-[#7e7e7e] text-[11px] mb-1">P/BV RATIO</div>
                  <div className="text-[#eeeeee] font-bold text-[16px]">
                    {stats?.pbv_ratio !== undefined ? `${stats.pbv_ratio}×` : '—'}
                  </div>
                  <div className="text-[#7e7e7e] text-[11px] mt-0.5">Price / Book Value</div>
                </div>

                <div className="border border-[#202020] bg-[#111111] p-3.5 rounded-[2px]">
                  <div className="text-[#7e7e7e] text-[11px] mb-1">ROE (PROFITABILITY)</div>
                  <div className="text-[#eeeeee] font-bold text-[16px]">
                    {stats?.roe !== undefined ? `${stats.roe}%` : '—'}
                  </div>
                  <div className="text-[#7e7e7e] text-[11px] mt-0.5">Return on Equity</div>
                </div>

                <div className="border border-[#202020] bg-[#111111] p-3.5 rounded-[2px]">
                  <div className="text-[#da5c2c] text-[11px] mb-1">DIVIDEND YIELD</div>
                  <div className="text-[#da5c2c] font-bold text-[16px]">
                    {stats?.dividend_yield !== undefined ? `${stats.dividend_yield}%` : '—'}
                  </div>
                  <div className="text-[#7e7e7e] text-[11px] mt-0.5">Annual Payout</div>
                </div>

                <div className="border border-[#202020] bg-[#111111] p-3.5 rounded-[2px]">
                  <div className="text-[#7e7e7e] text-[11px] mb-1">EPS (TTM)</div>
                  <div className="text-[#eeeeee] font-bold text-[16px]">
                    {stats?.eps !== undefined ? `Rp ${stats.eps.toLocaleString()}` : '—'}
                  </div>
                  <div className="text-[#7e7e7e] text-[11px] mt-0.5">Per Share</div>
                </div>

                <div className="border border-[#202020] bg-[#111111] p-3.5 rounded-[2px]">
                  <div className="text-[#7e7e7e] text-[11px] mb-1">MARKET CAP</div>
                  <div className="text-[#eeeeee] font-bold text-[16px]">
                    {stats?.market_cap ? (typeof stats.market_cap === 'number' ? `Rp ${(stats.market_cap / 1e12).toFixed(1)}T` : `Rp ${stats.market_cap}`) : '—'}
                  </div>
                  <div className="text-[#7e7e7e] text-[11px] mt-0.5">Total Valuation</div>
                </div>
              </div>

              {/* Secondary Factors */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="border border-[#202020] bg-[#111111] p-3 rounded-[2px]">
                  <div className="text-[#7e7e7e] text-[11px]">PIOTROSKI F-SCORE</div>
                  <div className="text-[#eeeeee] font-bold text-[15px] mt-1">{stats?.piotroski_f_score ?? '—'} / 9</div>
                </div>
                <div className="border border-[#202020] bg-[#111111] p-3 rounded-[2px]">
                  <div className="text-[#7e7e7e] text-[11px]">NET PROFIT MARGIN</div>
                  <div className="text-[#eeeeee] font-bold text-[15px] mt-1">{stats?.npm ?? '—'}%</div>
                </div>
                <div className="border border-[#202020] bg-[#111111] p-3 rounded-[2px]">
                  <div className="text-[#7e7e7e] text-[11px]">NET INCOME (TTM)</div>
                  <div className="text-[#eeeeee] font-bold text-[15px] mt-1">Rp {stats?.net_income || '—'}</div>
                </div>
                <div className="border border-[#202020] bg-[#111111] p-3 rounded-[2px]">
                  <div className="text-[#7e7e7e] text-[11px]">FREE FLOAT</div>
                  <div className="text-[#eeeeee] font-bold text-[15px] mt-1">{stats?.free_float || '—'}</div>
                </div>
              </div>

              {/* Corporate Profile Card */}
              {profile && (
                <div className="border border-[#202020] bg-[#111111] rounded-[2px] p-4 space-y-3">
                  <div className="flex justify-between border-b border-[#202020] pb-2 text-[#b4b4b4] text-[12px] font-bold">
                    <span>CORPORATE PROFILE · {profile.name}</span>
                    <code className="text-[#7e7e7e] text-[11px]">IPO: {profile.listing_date || '—'}</code>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-[12px]">
                    <div>
                      <div className="text-[#7e7e7e] text-[11px]">HEADQUARTERS ADDRESS</div>
                      <div className="text-[#eeeeee] leading-relaxed mt-1">{profile.address || '—'}</div>
                    </div>
                    <div>
                      <div className="text-[#7e7e7e] text-[11px]">INVESTOR RELATIONS</div>
                      <div className="text-[#eeeeee] mt-1">{profile.email || '—'}</div>
                      <div className="text-[#7e7e7e]">{profile.phone || ''}</div>
                      {profile.website && <div className="text-[#da5c2c]">{profile.website}</div>}
                    </div>
                    <div>
                      <div className="text-[#7e7e7e] text-[11px]">INDUSTRY SECTOR</div>
                      <div className="text-[#eeeeee] mt-1">{profile.sector || '—'}</div>
                      <div className="text-[#7e7e7e]">{profile.subsector || ''}</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeSubTab === 'statements' && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3 p-3 bg-[#000000] border border-[#202020] rounded-[2px]">
                <div className="flex items-center gap-2">
                  <span className="text-[#7e7e7e] text-[12px]">Report:</span>
                  {[
                    { id: 1, label: 'Income Statement' },
                    { id: 2, label: 'Balance Sheet' },
                    { id: 3, label: 'Cash Flow' },
                  ].map((r) => (
                    <button
                      key={r.id}
                      onClick={() => setReportType(r.id)}
                      className={`btn-action-sm ${reportType === r.id ? 'active' : ''}`}
                    >
                      {r.label}
                    </button>
                  ))}
                </div>

                <div className="flex items-center gap-2">
                  <span className="text-[#7e7e7e] text-[12px]">Period:</span>
                  {[
                    { id: 1, label: 'Quarterly' },
                    { id: 2, label: 'Annual' },
                    { id: 3, label: 'TTM' },
                  ].map((s) => (
                    <button
                      key={s.id}
                      onClick={() => setStatementType(s.id)}
                      className={`btn-action-sm ${statementType === s.id ? 'active' : ''}`}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Clean Structured Financial Table */}
              <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
                <div className="p-2.5 bg-[#191919] border-b border-[#202020] flex justify-between items-center text-[11px] text-[#7e7e7e]">
                  <span>Currency: {financials?.currency || 'IDR'} · ({financials?.unit || 'In Million'})</span>
                  <span>Showing Latest {recentPeriods.length} Reporting Periods</span>
                </div>

                {lineItems.length === 0 ? (
                  <div className="p-8 text-center text-[#7e7e7e]">No financial report available for selected filters.</div>
                ) : (
                  <div className="overflow-x-auto max-h-[520px]">
                    <table className="w-full text-left font-mono text-[12px]">
                      <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4] sticky top-0 z-10">
                        <tr>
                          <th className="py-2.5 px-3 font-normal min-w-[240px]">FINANCIAL LINE ITEM</th>
                          {recentPeriods.map((p) => (
                            <th key={p} className="py-2.5 px-3 font-normal text-right whitespace-nowrap min-w-[120px]">
                              {p}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
                        {lineItems.map((item, idx) => {
                          const isHeading = item.name.toUpperCase().startsWith('TOTAL') || item.name.toUpperCase().startsWith('LABA');
                          const itemValues = item.values || [];
                          // Match last N values to recentPeriods
                          const recentVals = itemValues.slice(-recentPeriods.length);

                          return (
                            <tr key={idx} className={`hover:bg-[#191919] transition-colors ${isHeading ? 'bg-[#141414] font-bold' : ''}`}>
                              <td className={`py-2 px-3 ${isHeading ? 'text-[#eeeeee] font-bold' : 'text-[#b4b4b4]'}`}>
                                {item.name}
                              </td>
                              {recentVals.map((val: string, vIdx: number) => {
                                const num = parseFloat(val);
                                const isNegative = !isNaN(num) && num < 0;
                                let formatted = val;
                                if (!isNaN(num) && val !== '-') {
                                  const absNum = Math.abs(num);
                                  if (absNum >= 1e12) {
                                    formatted = `${(num / 1e12).toFixed(2)}T`;
                                  } else if (absNum >= 1e9) {
                                    formatted = `${(num / 1e9).toFixed(1)}B`;
                                  } else if (absNum >= 1e6) {
                                    formatted = `${(num / 1e6).toFixed(1)}M`;
                                  } else {
                                    formatted = num.toLocaleString();
                                  }
                                }

                                return (
                                  <td
                                    key={vIdx}
                                    className={`py-2 px-3 text-right whitespace-nowrap ${
                                      isNegative ? 'text-[#da5c2c]' : isHeading ? 'text-[#eeeeee]' : 'text-[#b4b4b4]'
                                    }`}
                                  >
                                    {formatted === '-' ? '—' : formatted}
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeSubTab === 'subsidiaries' && (
            <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
              <table className="w-full text-left font-mono text-[12px]">
                <thead className="bg-[#191919] border-b border-[#202020] text-[#b4b4b4]">
                  <tr>
                    <th className="py-2.5 px-3 font-normal">SUBSIDIARY NAME</th>
                    <th className="py-2.5 px-3 font-normal">BUSINESS LINE</th>
                    <th className="py-2.5 px-3 font-normal">LOCATION</th>
                    <th className="py-2.5 px-3 font-normal text-right">OWNERSHIP (%)</th>
                    <th className="py-2.5 px-3 font-normal text-right">TOTAL ASSETS (B RP)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#202020] text-[#eeeeee]">
                  {subsidiaries.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="p-4 text-center text-[#7e7e7e]">
                        No subsidiaries recorded for {selectedSymbol}.
                      </td>
                    </tr>
                  ) : (
                    subsidiaries.map((s: any, idx: number) => (
                      <tr key={idx} className="hover:bg-[#191919] transition-colors">
                        <td className="py-2 px-3 font-bold text-[#eeeeee]">{s.company_name}</td>
                        <td className="py-2 px-3 text-[#b4b4b4]">{s.business_type}</td>
                        <td className="py-2 px-3 text-[#7e7e7e]">{s.location}</td>
                        <td className="py-2 px-3 text-right text-[#da5c2c] font-bold">{s.percentage}%</td>
                        <td className="py-2 px-3 text-right text-[#b4b4b4]">{s.total_assets}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
};
