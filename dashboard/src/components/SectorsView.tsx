import React, { useState, useEffect } from 'react';
import { fetchSectors, fetchSubsectors, fetchSectorCompanies, getStoredBackendUrl } from '../services/api';
import { SectorItem, SubsectorItem, SectorCompany } from '../types/datafeed';
import { ApiSpecDrawer } from './ApiSpecDrawer';

export const SectorsView: React.FC = () => {
  const [sectors, setSectors] = useState<SectorItem[]>([]);
  const [selectedSectorId, setSelectedSectorId] = useState<string>('1');
  const [subsectors, setSubsectors] = useState<SubsectorItem[]>([]);
  const [selectedSubsectorId, setSelectedSubsectorId] = useState<string | null>(null);
  const [companies, setCompanies] = useState<SectorCompany[]>([]);
  const [loadingSectors, setLoadingSectors] = useState<boolean>(true);
  const [loadingSubsectors, setLoadingSubsectors] = useState<boolean>(false);
  const [loadingCompanies, setLoadingCompanies] = useState<boolean>(false);

  // 1. Load sectors list
  useEffect(() => {
    let mounted = true;
    setLoadingSectors(true);

    const loadData = async () => {
      const data = await fetchSectors(getStoredBackendUrl());
      if (mounted) {
        setSectors(data);
        if (data.length > 0 && !selectedSectorId) {
          setSelectedSectorId(data[0].id);
        }
        setLoadingSectors(false);
      }
    };

    loadData();
    return () => {
      mounted = false;
    };
  }, []);

  // 2. Load subsectors whenever selectedSectorId changes
  useEffect(() => {
    if (!selectedSectorId) return;
    let mounted = true;
    setLoadingSubsectors(true);
    setCompanies([]);
    setSelectedSubsectorId(null);

    const loadSub = async () => {
      const subs = await fetchSubsectors(selectedSectorId, getStoredBackendUrl());
      if (mounted) {
        setSubsectors(subs);
        if (subs.length > 0) {
          setSelectedSubsectorId(subs[0].id);
        }
        setLoadingSubsectors(false);
      }
    };

    loadSub();
    return () => {
      mounted = false;
    };
  }, [selectedSectorId]);

  // 3. Load companies whenever selectedSubsectorId changes
  useEffect(() => {
    if (!selectedSectorId || !selectedSubsectorId) return;
    let mounted = true;
    setLoadingCompanies(true);

    const loadComp = async () => {
      const list = await fetchSectorCompanies(selectedSectorId, selectedSubsectorId, getStoredBackendUrl());
      if (mounted) {
        setCompanies(list);
        setLoadingCompanies(false);
      }
    };

    loadComp();
    return () => {
      mounted = false;
    };
  }, [selectedSectorId, selectedSubsectorId]);


  return (
    <div className="space-y-4 font-mono text-[13px]">
      {/* Interactive API Spec Drawer */}
      <ApiSpecDrawer
        method="GET"
        endpoint="/v1/sectors"
        queryParams={`/v1/sectors/${selectedSectorId}/subsectors · /v1/sectors/${selectedSectorId}/subsectors/${selectedSubsectorId || '10'}/companies`}
        useCaseTitle="Taxonomy, Correlation & Sector Rotation"
        useCaseDescription="Classifies the entire Indonesian stock exchange into hierarchical industry sectors, subsectors, and constituent equities. Essential for macroeconomic sector rotation models, thematic ETF basket creation, and sector beta covariance matrices."
        curlCommand={`curl -s "http://127.0.0.1:8000/v1/sectors"`}
        responsePreview={`{
  "sectors": [
    { "id": "1", "name": "Barang Konsumen Primer", "alias1": "barang-konsumen-primer" }
  ]
}`}
      />

      {/* 3-Column Hierarchy Explorer */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Left: Sectors List */}
        <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
          <div className="bg-[#191919] border-b border-[#202020] px-4 py-2.5 text-[#b4b4b4] text-[12px] font-bold">
            IDX SECTORS ({sectors.length})
          </div>
          <div className="divide-y divide-[#202020] max-h-[480px] overflow-y-auto">
            {loadingSectors ? (
              <div className="p-4 text-center text-[#7e7e7e] text-[12px]">Loading sectors...</div>
            ) : (
              sectors.map((s) => {
                const isSelected = selectedSectorId === s.id;
                return (
                  <button
                    key={s.id}
                    onClick={() => setSelectedSectorId(s.id)}
                    className={`w-full text-left p-3 transition-colors flex items-center justify-between cursor-pointer ${
                      isSelected ? 'bg-[#191919] text-[#eeeeee]' : 'hover:bg-[#191919] text-[#b4b4b4]'
                    }`}
                  >
                    <div>
                      <div className="font-bold text-[#eeeeee] text-[12px]">{s.name}</div>
                      <div className="text-[#7e7e7e] text-[11px]">Sector ID: {s.id}</div>
                    </div>
                    {isSelected && (
                      <span className="text-[#da5c2c] text-[12px] font-bold">→</span>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Center: Subsectors Drilldown */}
        <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
          <div className="bg-[#191919] border-b border-[#202020] px-4 py-2.5 text-[#b4b4b4] text-[12px] font-bold flex justify-between items-center">
            <span>SUBSECTORS</span>
            <code className="text-[#7e7e7e] text-[10px]">ID: {selectedSectorId}</code>
          </div>
          <div className="divide-y divide-[#202020] max-h-[480px] overflow-y-auto">
            {loadingSubsectors ? (
              <div className="p-4 text-center text-[#7e7e7e] text-[12px]">Loading subsectors...</div>
            ) : subsectors.length === 0 ? (
              <div className="p-4 text-center text-[#7e7e7e] text-[12px]">No subsectors for this sector.</div>
            ) : (
              subsectors.map((sub) => {
                const isSelected = selectedSubsectorId === sub.id;
                return (
                  <button
                    key={sub.id}
                    onClick={() => setSelectedSubsectorId(sub.id)}
                    className={`w-full text-left p-3 transition-colors flex items-center justify-between cursor-pointer ${
                      isSelected ? 'bg-[#191919] text-[#eeeeee]' : 'hover:bg-[#191919] text-[#b4b4b4]'
                    }`}
                  >
                    <div>
                      <div className="font-bold text-[#eeeeee] text-[12px]">{sub.name}</div>
                      <div className="text-[#7e7e7e] text-[11px]">Subsector ID: {sub.id}</div>
                    </div>
                    {isSelected && (
                      <span className="text-[#da5c2c] text-[12px] font-bold">→</span>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Right: Constituent Equities */}
        <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden">
          <div className="bg-[#191919] border-b border-[#202020] px-4 py-2.5 text-[#b4b4b4] text-[12px] font-bold flex justify-between items-center">
            <span>CONSTITUENT STOCKS</span>
            <code className="text-[#7e7e7e] text-[10px]">{companies.length} stocks</code>
          </div>
          <div className="divide-y divide-[#202020] max-h-[480px] overflow-y-auto">
            {loadingCompanies ? (
              <div className="p-4 text-center text-[#7e7e7e] text-[12px]">Loading companies...</div>
            ) : companies.length === 0 ? (
              <div className="p-4 text-center text-[#7e7e7e] text-[12px]">Select a subsector to view stocks.</div>
            ) : (
              companies.map((c) => {
                const isPositive = parseFloat(c.change) >= 0;
                return (
                  <div key={c.symbol} className="p-3.5 flex items-center justify-between hover:bg-[#191919] text-[13px] transition-colors">
                    <div>
                      <div className="font-bold text-[#eeeeee] text-[13px]">{c.symbol}</div>
                      <div className="text-[#7e7e7e] text-[11px] truncate max-w-[130px]">{c.name}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-bold text-[#eeeeee] text-[13px]">
                        Rp {parseInt(c.last, 10).toLocaleString()}
                      </div>
                      <div className={`text-[11px] font-bold ${isPositive ? 'text-[#eeeeee]' : 'text-[#da5c2c]'}`}>
                        {isPositive ? `+${c.change}` : c.change} ({c.change_pct}%)
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
