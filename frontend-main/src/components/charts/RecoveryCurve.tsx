import { motion } from 'framer-motion';
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
} from 'recharts';
import { formatCurrencyCompact } from '../../lib/utils';
import type { RunMetrics } from '../../lib/types';

interface RecoveryCurveDataPoint {
  hour: number;
  baseline: number;
  smart: number;
}

interface RecoveryCurveProps {
  data: RecoveryCurveDataPoint[];
  height?: number;
  baselineMetrics?: RunMetrics;
  smartMetrics?: RunMetrics;
}

const tooltipStyle = {
  backgroundColor: '#1A211F',
  border: '1px solid #2A3330',
  color: '#F5F7F6',
  fontSize: '12px',
  borderRadius: '8px',
  padding: '10px 12px',
};

const tooltipItemStyle = {
  color: '#9CA3A0',
  fontSize: '11px',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
};

export function RecoveryCurve({
  data,
  height = 320,
  baselineMetrics,
  smartMetrics,
}: RecoveryCurveProps) {
  const hasBoth = baselineMetrics && smartMetrics;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2, duration: 0.5 }}
      className="w-full"
    >
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 4, right: 12, left: -12, bottom: 0 }}>
          <defs>
            <linearGradient id="baselineGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#9CA3A0" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#9CA3A0" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="smartGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#C9F35B" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#C9F35B" stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid
            stroke="#2A3330"
            strokeWidth={1}
            opacity={0.5}
            vertical={false}
          />
          <XAxis
            dataKey="hour"
            axisLine={false}
            tickLine={false}
            tick={{
              fill: '#6B6F6D',
              fontSize: 11,
              fontFamily: 'JetBrains Mono, monospace',
            }}
            tickFormatter={(value: number) => `${value}h`}
            dy={10}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{
              fill: '#6B6F6D',
              fontSize: 11,
              fontFamily: 'JetBrains Mono, monospace',
            }}
            tickFormatter={(value: number) => formatCurrencyCompact(value)}
            dx={-8}
          />
          <Tooltip
            contentStyle={tooltipStyle}
            itemStyle={tooltipItemStyle}
            cursor={{ stroke: '#2A3330', strokeWidth: 1, opacity: 0.5 }}
            formatter={(value: unknown, name: unknown) => [
              formatCurrencyCompact(value as number),
              name === 'baseline' ? 'Baseline' : 'SARA',
            ]}
            labelFormatter={(label: unknown) => `Hour ${label}`}
          />

          {hasBoth && (
            <ReferenceLine
              y={Number(baselineMetrics?.net_recovered_value)}
              stroke="#9CA3A0"
              strokeDasharray="4 2"
              opacity={0.4}
              label={{
                value: 'Baseline final',
                position: 'insideTopLeft',
                fill: '#9CA3A0',
                fontSize: 10,
                fontFamily: 'JetBrains Mono, monospace',
              }}
            />
          )}

          {hasBoth && (
            <ReferenceLine
              y={Number(smartMetrics?.net_recovered_value)}
              stroke="#C9F35B"
              strokeDasharray="4 2"
              opacity={0.5}
              label={{
                value: 'SARA final',
                position: 'insideTopRight',
                fill: '#C9F35B',
                fontSize: 10,
                fontFamily: 'JetBrains Mono, monospace',
              }}
            />
          )}

          <Line
            type="monotone"
            dataKey="baseline"
            stroke="#9CA3A0"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={true}
            animationDuration={1500}
            activeDot={{ r: 4, fill: '#9CA3A0', strokeWidth: 2, stroke: '#1A211F' }}
          />
          <Line
            type="monotone"
            dataKey="smart"
            stroke="#C9F35B"
            strokeWidth={2}
            dot={false}
            isAnimationActive={true}
            animationDuration={1500}
            animationBegin={0}
            activeDot={{ r: 5, fill: '#C9F35B', strokeWidth: 2, stroke: '#1A211F' }}
          />

          <Legend
            verticalAlign="top"
            align="right"
            iconSize={8}
            wrapperStyle={{
              paddingTop: 4,
              fontSize: '11px',
              fontFamily: 'JetBrains Mono, monospace',
            }}
            formatter={(value) => [
              value === 'baseline' ? 'BASELINE' : 'SARA',
            ]}
          />
        </LineChart>
      </ResponsiveContainer>
    </motion.div>
  );
}

// ── Simple progress curve ─────────────────────────

export function RecoveryProgressBar({
  percentage,
  label,
  color = 'chartreuse',
  height = 8,
}: {
  percentage: number;
  label?: string;
  color?: 'chartreuse' | 'money' | 'success' | 'warning' | 'error';
  height?: number;
}) {
  const colorMap = {
    chartreuse: '#C9F35B',
    money: '#E5A35D',
    success: '#10B981',
    warning: '#F59E0B',
    error: '#EF4444',
  };

  return (
    <div className="w-full">
      <div className="mb-1.5 flex items-center justify-between">
        {label && (
          <span className="text-xs font-medium text-secondary">{label}</span>
        )}
        <span className="font-mono text-xs text-tertiary">
          {percentage.toFixed(1)}%
        </span>
      </div>
      <div
        className="relative w-full overflow-hidden rounded-full bg-border-subtle"
        style={{ height }}
      >
        <motion.div
          className="h-full rounded-full"
          style={{
            backgroundColor: colorMap[color],
            width: `${Math.min(percentage, 100)}%`,
          }}
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(percentage, 100)}%` }}
          transition={{ duration: 1, ease: 'easeOut' }}
        />
      </div>
    </div>
  );
}

// ── Donut / ring chart ─────────────────────────────

export function RecoveryRing({
  percentage,
  size = 120,
  strokeWidth = 8,
  color = '#C9F35B',
  label,
  className,
}: {
  percentage: number;
  size?: number;
  strokeWidth?: number;
  color?: string;
  label?: string;
  className?: string;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (circumference * Math.min(percentage, 100)) / 100;

  return (
    <motion.div
      className={`relative flex flex-col items-center justify-center ${className || ''}`}
      style={{ width: size, height: size }}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5, delay: 0.1 }}
    >
      <svg width={size} height={size} className="transform -rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border-subtle)"
          strokeWidth={strokeWidth}
          opacity={0.3}
        />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 1s ease-out' }}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="font-mono text-xl font-bold text-primary">
          {percentage.toFixed(1)}%
        </span>
        {label && <span className="text-xs text-tertiary">{label}</span>}
      </div>
    </motion.div>
  );
}
