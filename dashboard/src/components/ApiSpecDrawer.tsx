import React, { useState } from 'react';

interface ApiSpecDrawerProps {
  method: 'GET' | 'POST' | 'WS';
  endpoint: string;
  queryParams?: string;
  useCaseTitle: string;
  useCaseDescription: string;
  curlCommand: string;
  responsePreview?: string;
}

export const ApiSpecDrawer: React.FC<ApiSpecDrawerProps> = ({
  method,
  endpoint,
  queryParams,
  useCaseTitle,
  useCaseDescription,
  curlCommand,
  responsePreview,
}) => {
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(curlCommand);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const methodColor = 
    method === 'GET' ? 'bg-[#202020] text-[#eeeeee]' :
    method === 'POST' ? 'bg-[#da5c2c] text-[#eeeeee]' :
    'bg-[#2a7fff] text-[#eeeeee]';

  return (
    <div className="border border-[#202020] bg-[#111111] rounded-[2px] overflow-hidden font-mono text-[12px] mb-4">
      {/* Header Bar */}
      <div 
        onClick={() => setIsOpen(!isOpen)}
        className="p-3 bg-[#191919] hover:bg-[#202020] transition-colors cursor-pointer flex flex-col sm:flex-row sm:items-center justify-between gap-2 select-none"
      >
        <div className="flex items-center gap-2.5">
          <span className={`px-2 py-0.5 rounded-[2px] font-bold text-[11px] ${methodColor}`}>
            {method}
          </span>
          <code className="text-[#eeeeee] font-bold text-[13px]">
            {endpoint}
          </code>
          {queryParams && (
            <span className="text-[#7e7e7e] text-[11px] hidden md:inline">
              {queryParams}
            </span>
          )}
        </div>

        <div className="flex items-center gap-3 text-[11px]">
          <span className="text-[#da5c2c] font-bold uppercase tracking-wider">
            {useCaseTitle}
          </span>
          <span className="text-[#7e7e7e]">{isOpen ? '▲ Hide Spec' : '▼ Explore API'}</span>
        </div>
      </div>

      {/* Expanded Spec Drawer */}
      {isOpen && (
        <div className="p-4 bg-[#000000] border-t border-[#202020] space-y-3">
          {/* Use Case Explanation */}
          <div>
            <div className="text-[#7e7e7e] text-[11px] font-bold uppercase mb-1">
              What this data is used for
            </div>
            <p className="text-[#b4b4b4] text-[12px] leading-relaxed">
              {useCaseDescription}
            </p>
          </div>

          {/* cURL Command */}
          <div>
            <div className="flex items-center justify-between text-[#7e7e7e] text-[11px] font-bold uppercase mb-1">
              <span>cURL Command</span>
              <button
                onClick={handleCopy}
                className="text-[#eeeeee] hover:text-[#da5c2c] cursor-pointer"
              >
                {copied ? '✓ Copied' : 'Copy cURL'}
              </button>
            </div>
            <pre className="p-2.5 bg-[#111111] border border-[#202020] rounded-[2px] text-[#eeeeee] text-[11px] overflow-x-auto">
              {curlCommand}
            </pre>
          </div>

          {/* Response Structure */}
          {responsePreview && (
            <div>
              <div className="text-[#7e7e7e] text-[11px] font-bold uppercase mb-1">
                Schema & Field Meaning
              </div>
              <pre className="p-2.5 bg-[#111111] border border-[#202020] rounded-[2px] text-[#b4b4b4] text-[11px] overflow-x-auto max-h-48 overflow-y-auto">
                {responsePreview}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
