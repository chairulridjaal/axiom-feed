import React, { useState, useEffect } from 'react';

interface LogBarHistogramProps {
  label?: string;
  count?: number;
}

export const LogBarHistogram: React.FC<LogBarHistogramProps> = ({
  label = 'EVENT VOLUME (TOKIO BROADCAST / HUB DISPATCH)',
  count = 184520,
}) => {
  // 36 bars representing streaming event density
  const [bars, setBars] = useState<number[]>([
    16, 24, 32, 20, 38, 48, 32, 22, 28, 42, 54, 62, 44, 28, 36, 52, 68, 58, 40, 32,
    46, 64, 72, 48, 36, 42, 58, 50, 32, 38, 52, 60, 44, 28, 36, 48
  ]);

  useEffect(() => {
    const interval = setInterval(() => {
      setBars((prev) => {
        const nextVal = Math.floor(Math.random() * 55) + 15;
        return [...prev.slice(1), nextVal];
      });
    }, 1400);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="bg-[#111111] border-b border-[#202020] px-4 py-3 flex items-center justify-between font-mono text-[12px]">
      <div className="flex items-center gap-2 text-[#7e7e7e]">
        <span>{label}</span>
        <span className="text-[#3a3a3a]">·</span>
        <span className="text-[#eeeeee] font-bold">{count.toLocaleString()} msgs</span>
      </div>

      {/* Tight row of rectangular bars in #2a7fff (DESIGN.md:167-172) */}
      <div className="flex items-end gap-[3px] h-[16px]">
        {bars.map((h, i) => {
          const isLatest = i >= bars.length - 2;
          return (
            <div
              key={i}
              className="w-[4px] rounded-[1px] transition-all duration-300"
              style={{
                height: `${Math.max((h / 75) * 16, 3)}px`,
                backgroundColor: isLatest ? '#da5c2c' : '#2a7fff',
                opacity: isLatest ? 1 : 0.75,
              }}
            />
          );
        })}
      </div>
    </div>
  );
};
