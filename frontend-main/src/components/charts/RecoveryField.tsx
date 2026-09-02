import { motion } from 'framer-motion';
import { useMemo, useState } from 'react';
import { formatCurrencyCompact } from '../../lib/utils';
import type { RunMetrics } from '../../lib/types';

/**
 * RecoveryField — constellation visualization.
 *
 * A particle/field canvas that represents recovery flow as nodes
 * (cases) connected by luminous paths (retries). Hover reveals
 * individual case status and expected recovery value.
 */

export interface FieldNodeData {
  id: string;
  x: number; // 0-100
  y: number; // 0-100
  value: number;
  status: 'recovered' | 'pending' | 'stopped' | 'failed';
  size?: number; // 1-10
}

interface RecoveryFieldProps {
  metrics?: RunMetrics;
  nodes?: FieldNodeData[];
  height?: number;
  interactive?: boolean;
  showStats?: boolean;
}

const STATUS_COLORS = {
  recovered: '#10B981',
  pending: '#C9F35B',
  stopped: '#F59E0B',
  failed: '#EF4444',
} as const;

export function RecoveryField({
  metrics,
  nodes: externalNodes,
  height = 280,
  interactive = true,
  showStats = true,
}: RecoveryFieldProps) {
  const [hoveredNode, setHoveredNode] = useState<FieldNodeData | null>(null);

  // Generate field nodes from metrics if not provided
  const nodes = useMemo<FieldNodeData[]>(() => {
    if (externalNodes) return externalNodes;
    if (!metrics) return [];

    const { total_cases, recovered_cases, stop_count } = metrics;
    const fieldNodes: FieldNodeData[] = [];
    const seed = (s: number) => ((s * 9301 + 49297) % 233280) / 233280;

    let seedIdx = 42;
    let r = (n: number) => seed((seedIdx += n));

    // Recovered nodes (green)
    for (let i = 0; i < recovered_cases; i++) {
      fieldNodes.push({
        id: `recovered-${i}`,
        x: r(i) * 100,
        y: r(i * 2) * 100,
        value: (parseFloat(metrics?.total_recovered_value || '0') / recovered_cases) * Math.random(),
        status: 'recovered',
        size: 1 + Math.random() * 3,
      });
    }

    // Pending / stopped nodes (chartreuse / amber)
    const remaining = total_cases - recovered_cases;
    const stoppedCount = stop_count;
    const pendingCount = Math.max(remaining - stoppedCount, 0);

    for (let i = 0; i < stoppedCount; i++) {
      fieldNodes.push({
        id: `stopped-${i}`,
        x: r(i + 500) * 100,
        y: r(i * 3 + 300) * 100,
        value: parseFloat(metrics?.total_recovered_value || '0') * Math.random() * 0.3,
        status: 'stopped',
        size: 1 + Math.random() * 2,
      });
    }

    for (let i = 0; i < pendingCount; i++) {
      fieldNodes.push({
        id: `pending-${i}`,
        x: r(i + 800) * 100,
        y: r(i * 5 + 600) * 100,
        value: 0,
        status: 'pending',
        size: 1 + Math.random() * 2.5,
      });
    }

    return fieldNodes.slice(0, Math.min(fieldNodes.length, 150)); // cap at 150 nodes for performance
  }, [metrics, externalNodes]);

  // Generate connections (lines between nearby nodes)
  const connections = useMemo(() => {
    if (nodes.length === 0) return [];
    const result: { from: number; to: number }[] = [];

    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < Math.min(i + 8, nodes.length); j++) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 12 && Math.random() > 0.3) {
          result.push({ from: i, to: j });
        }
      }
    }
    return result;
  }, [nodes]);

  return (
    <div
      className="relative w-full overflow-hidden rounded-xl border border-border-subtle bg-elevated"
      style={{ height }}
    >
      {/* SVG canvas */}
      <svg
        className="h-full w-full"
        preserveAspectRatio="none"
        viewBox="0 0 100 100"
        aria-label="Recovery field visualization"
      >
        {/* Gradient background */}
        <defs>
          <radialGradient id="field-gradient" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#111615" />
            <stop offset="100%" stopColor="#0A0D0C" />
          </radialGradient>
          <linearGradient id="connection-gradient" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#C9F35B" stopOpacity="0.3" />
            <stop offset="100%" stopColor="#10B981" stopOpacity="0.15" />
          </linearGradient>
        </defs>

        <rect width="100" height="100" fill="url(#field-gradient)" />

        {/* Connection lines */}
        {connections.map((conn, i) => (
          <line
            key={`conn-${i}`}
            x1={nodes[conn.from]?.x ?? 0}
            y1={nodes[conn.from]?.y ?? 0}
            x2={nodes[conn.to]?.x ?? 0}
            y2={nodes[conn.to]?.y ?? 0}
            stroke="url(#connection-gradient)"
            strokeWidth="0.15"
            opacity="0.4"
          />
        ))}

        {/* Grid pattern overlay */}
        <path
          d={generateGridPath()}
          stroke="#2A3330"
          strokeWidth="0.1"
          opacity="0.2"
          fill="none"
        />

        {/* Scan line animation */}
        <motion.rect
          x="0"
          y="0"
          width="100%"
          height="1"
          fill="rgba(201, 243, 91, 0.1)"
          animate={{ y: [0, 100] }}
          transition={{ duration: 4, repeat: Infinity, ease: 'linear' }}
        />

        {/* Nodes */}
        {nodes.map((node, i) => {
          const color = STATUS_COLORS[node.status];
          return (
            <motion.circle
              key={node.id}
              r={node.size ?? 1.5}
              cx={node.x}
              cy={node.y}
              fill={color}
              opacity={node.status === 'recovered' ? 0.9 : 0.7}
              initial={{ opacity: 0, scale: 0 }}
              animate={{ opacity: node.status === 'recovered' ? 0.9 : 0.7, scale: 1 }}
              transition={{ delay: i * 0.003, duration: 0.4 }}
              whileHover={interactive ? { r: (node.size ?? 1.5) + 2, opacity: 1 } : undefined}
              style={{ cursor: interactive ? 'pointer' : 'default' }}
              onMouseEnter={() => interactive && setHoveredNode(node)}
              onMouseLeave={() => interactive && setHoveredNode(null)}
            >
              {node.status === 'recovered' && (
                <motion.title>{node.id}</motion.title>
              )}
            </motion.circle>
          );
        })}

        {/* Glowing recovered nodes */}
        {nodes.filter((n) => n.status === 'recovered').map((node, i) => (
          <motion.circle
            key={`glow-${node.id}`}
            r={(node.size ?? 1.5) + 1}
            cx={node.x}
            cy={node.y}
            fill="none"
            stroke={STATUS_COLORS.recovered}
            strokeWidth="0.2"
            opacity="0"
            animate={{
              opacity: [0, 0.4, 0],
              r: [(node.size ?? 1.5) + 1, (node.size ?? 1.5) + 2.5, (node.size ?? 1.5) + 1],
            }}
            transition={{
              duration: 2 + i * 0.02,
              repeat: Infinity,
              repeatType: 'reverse',
            }}
          />
        ))}
      </svg>

      {/* Hover tooltip */}
      {hoveredNode && (
        <motion.div
          className="absolute rounded-lg border border-border-strong bg-panel px-3 py-2 text-xs"
          style={{
            left: `${hoveredNode.x}%`,
            top: `${hoveredNode.y}%`,
            transform: 'translate(-50%, -120%)',
            pointerEvents: 'none',
          }}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
        >
          <p className="font-medium text-primary">{hoveredNode.status}</p>
          <p className="text-tertiary">Value: {formatCurrencyCompact(hoveredNode.value)}</p>
        </motion.div>
      )}

      {/* Stats overlay */}
      {showStats && metrics && (
        <div className="absolute bottom-3 right-3 flex gap-3 rounded-lg bg-elevated/80 border border-border-subtle px-3 py-2 backdrop-blur-sm">
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full bg-success" />
            <span className="font-mono text-xs text-success">
              {metrics.recovered_cases}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full bg-chartreuse" />
            <span className="font-mono text-xs text-chartreuse">
              {metrics.total_cases - metrics.recovered_cases - metrics.stop_count}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-2 w-2 rounded-full bg-warning" />
            <span className="font-mono text-xs text-warning">
              {metrics.stop_count}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function generateGridPath(): string {
  const lines: string[] = [];
  for (let i = 0; i <= 20; i++) {
    const pos = (i / 20) * 100;
    lines.push(`M${pos} 0 L${pos} 100`);
    lines.push(`M0 ${pos} L100 ${pos}`);
  }
  return lines.join(' ');
}
