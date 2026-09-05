import React, { useState, useEffect } from 'react';
import { fetchLiveQuote, fetchLiveBook, getStoredBackendUrl } from '../services/api';
import { Quote, Book } from '../types/datafeed';
import { ApiSpecDrawer } from './ApiSpecDrawer';

interface ProtoViewProps {
  selectedSymbol: string;
}

export const ProtoView: React.FC<ProtoViewProps> = ({ selectedSymbol }) => {
  const [msgType, setMsgType] = useState<'liveprice' | 'pipe' | 'body'>('liveprice');
  const [quote, setQuote] = useState<Quote | null>(null);
  const [book, setBook] = useState<Book | null>(null);
  const [pipeSnapshot, setPipeSnapshot] = useState<string>('');

  useEffect(() => {
    let mounted = true;

    const loadData = async () => {
      const [q, b] = await Promise.all([
        fetchLiveQuote(selectedSymbol, getStoredBackendUrl()),
        fetchLiveBook(selectedSymbol, getStoredBackendUrl()),
      ]);
      if (mounted) {
        if (q) setQuote(q);
        if (b) {
          setBook(b);
          // Generate realistic pipe string from real book
          const bidParts = b.bids.slice(0, 5).map((l) => `${l.price};${l.lots};${parseInt(l.price || '0', 10) * l.lots * 100}`).join('|');
          const askParts = b.asks.slice(0, 5).map((l) => `${l.price};${l.lots};${parseInt(l.price || '0', 10) * l.lots * 100}`).join('|');
          setPipeSnapshot(`#O|${selectedSymbol}|BID|${bidParts}|OFFER|${askParts}`);
        }
      }
    };

    loadData();
    return () => {
      mounted = false;
    };
  }, [selectedSymbol]);

  return (
    <div className="space-y-4 font-mono text-[13px]">
      {/* Interactive API Spec Drawer */}
      <ApiSpecDrawer
        method="WS"
        endpoint="shared/proto/datafeed.proto"
        queryParams="Tag 9 (LivePrice) · Tag 6 (OrderBookBody) · Tag 10 (Orderbook Pipe)"
        useCaseTitle="Zero-GC Binary Decompression & Wire Decoding"
        useCaseDescription="Dissects upstream compressed zlib raw deflate packets decoded in ~10µs by Rust ingest-rs via prost into structured Protobuf messages. Normalized by Python api-py into domain decimal types without floating point imprecision."
        curlCommand={`protoc --proto_path=shared/proto --decode=datafeed.MarketEvent shared/proto/datafeed.proto < packet.bin`}
        responsePreview={`message LivePrice {
  string stock = 1;      // "${selectedSymbol}"
  double price = 2;      // ${quote?.last || '6675'}
  double volume = 3;     // ${quote?.volume || 45000000}
  double high = 4;       // ${quote?.high || '6700'}
  double low = 5;        // ${quote?.low || '6625'}
  double prev_close = 6; // ${quote?.prev_close || '6600'}
  double frequency = 7;  // ${quote?.freq || 12400}
}`}
      />

      {/* Selector */}
      <div className="flex items-center gap-2 p-3.5 bg-[#000000] border border-[#202020] rounded-[2px]">
        <span className="text-[#7e7e7e]">Message Type:</span>
        <button
          onClick={() => setMsgType('liveprice')}
          className={`btn-action-sm ${msgType === 'liveprice' ? 'active' : ''}`}
        >
          LivePrice (Proto Tag 9)
        </button>
        <button
          onClick={() => setMsgType('pipe')}
          className={`btn-action-sm ${msgType === 'pipe' ? 'active' : ''}`}
        >
          Legacy Pipe (#O Tag 10)
        </button>
        <button
          onClick={() => setMsgType('body')}
          className={`btn-action-sm ${msgType === 'body' ? 'active' : ''}`}
        >
          OrderBookBody (Proto Tag 6)
        </button>
      </div>

      {msgType === 'liveprice' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Wire Schema */}
          <div className="border border-[#202020] bg-[#111111] p-4 rounded-[2px]">
            <div className="text-[#b4b4b4] text-[12px] pb-2.5 border-b border-[#202020] mb-3 font-bold">
              Wire Protobuf Message (datafeed.proto:64-81)
            </div>
            <pre className="text-[#b4b4b4] text-[12px] leading-relaxed overflow-x-auto">
{`message LivePrice {
  string stock = 1;           // "${selectedSymbol}"
  double price = 2;           // ${quote?.last || '6675'}
  double volume = 3;          // ${quote?.volume || 0}
  double high = 4;            // ${quote?.high || 'null'}
  double low = 5;             // ${quote?.low || 'null'}
  double prev_close = 6;      // ${quote?.prev_close || 'null'}
  double frequency = 7;       // ${quote?.freq || 0}
  double average = 10;        // ${quote?.avg || 'null'}
  string time_str = 11;       // "${quote?.ts || ''}"
  double open = 12;           // ${quote?.open || 'null'}
  double value = 14;          // ${quote?.value || '0'}
  int32 is_index = 17;        // ${quote?.is_index ? 1 : 0}
}`}
            </pre>
          </div>

          {/* Domain Model */}
          <div className="border border-[#202020] bg-[#111111] p-4 rounded-[2px]">
            <div className="text-[#b4b4b4] text-[12px] pb-2.5 border-b border-[#202020] mb-3 font-bold">
              Normalized Domain Model (mapping.py:135-187)
            </div>
            <pre className="text-[#eeeeee] text-[12px] leading-relaxed overflow-x-auto">
              {JSON.stringify(quote, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {msgType === 'pipe' && (
        <div className="space-y-4">
          <div className="border border-[#202020] bg-[#111111] p-4 rounded-[2px]">
            <div className="text-[#b4b4b4] text-[12px] pb-2.5 border-b border-[#202020] mb-3 font-bold">
              Legacy #O Pipe Snapshot (mapping.py:parse_legacy_orderbook_pipe)
            </div>
            <pre className="text-[#eeeeee] text-[12px] overflow-x-auto whitespace-pre-wrap">
              {pipeSnapshot || '(no book data)'}
            </pre>
          </div>

          <div className="border border-[#202020] bg-[#111111] p-4 rounded-[2px]">
            <div className="text-[#b4b4b4] text-[12px] pb-2.5 border-b border-[#202020] mb-3 font-bold">
              Parsed Book Domain Output
            </div>
            <pre className="text-[#eeeeee] text-[12px] overflow-x-auto">
              {JSON.stringify(book, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {msgType === 'body' && (
        <div className="border border-[#202020] bg-[#111111] p-4 rounded-[2px]">
          <div className="text-[#b4b4b4] text-[12px] pb-2.5 border-b border-[#202020] mb-3 font-bold">
            Pure Protobuf OrderBookBody Schema (datafeed.proto:101-118)
          </div>
          <pre className="text-[#b4b4b4] text-[12px] leading-relaxed overflow-x-auto">
{`message OrderBookBody {
  string stock_symbol = 1;  // "${selectedSymbol}"
  repeated Bid bid = 2;     // ${JSON.stringify(book?.bids.slice(0, 3) || [])}
  repeated Offer offer = 3; // ${JSON.stringify(book?.asks.slice(0, 3) || [])}
  google.protobuf.Timestamp time = 4;
}`}
          </pre>
        </div>
      )}
    </div>
  );
};
