import { BaseEdge, type EdgeProps, getBezierPath } from "@xyflow/react";

/** A workflow edge with three live states (set via `data.state`):
 *  - "active"    → solid primary + a travelling dot (the route this turn took) — the "alive" effect
 *  - "traversed" → solid primary (a route taken earlier this session)
 *  - "idle"      → faint dashed (not yet used)
 *  Uses SVG <animateMotion> to move a dot along the bezier path (React Flow's recommended technique). */
export function PulseEdge({
  id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, data,
}: EdgeProps) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const state = (data?.state as string) ?? "idle";
  const active = state === "active";
  const live = active || state === "traversed";

  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        style={{
          stroke: live ? "hsl(var(--primary))" : "hsl(var(--muted))",
          strokeWidth: active ? 3 : live ? 2 : 1.5,
          strokeDasharray: live ? undefined : "4 4",
          opacity: live ? 1 : 0.35,
        }}
      />
      {active && (
        <>
          {/* soft glow trailing the dot, then the bright dot on top */}
          <circle r="9" fill="hsl(var(--primary))" opacity="0.18">
            <animateMotion dur="1.3s" repeatCount="indefinite" path={path} />
          </circle>
          <circle r="4.5" fill="hsl(var(--primary))">
            <animateMotion dur="1.3s" repeatCount="indefinite" path={path} />
          </circle>
        </>
      )}
    </>
  );
}

export const pulseEdgeTypes = { pulse: PulseEdge };
