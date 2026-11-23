import type { Entity, Relationship } from "../../api/advanced";

/**
 * Characters set round a ring, relationships drawn between them. A picture of the list next to it:
 * everything here is also in that list, so the map is hidden from screen readers apart from a summary.
 */
export function RelationshipMap({
  people,
  relationships,
}: {
  people: Entity[];
  relationships: Relationship[];
}) {
  if (people.length < 2) {
    return <p className="muted">Add at least two characters to draw the map.</p>;
  }
  const W = 640;
  const H = Math.max(360, 120 + people.length * 22);
  const cx = W / 2;
  const cy = H / 2;
  const r = Math.min(W, H) / 2 - 70;
  const pos = new Map(
    people.map((p, i) => {
      const a = (2 * Math.PI * i) / people.length - Math.PI / 2;
      return [p.id, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a), a }];
    }),
  );
  const drawn = relationships.filter((rel) => pos.has(rel.from_entity_id) && pos.has(rel.to_entity_id));
  const summary = `${people.length} characters and ${drawn.length} relationships. The same information is in the list above.`;
  return (
    <figure className="rel-map">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary}>
        <defs>
          <marker
            id="rel-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" className="rel-arrowhead" />
          </marker>
        </defs>
        <circle cx={cx} cy={cy} r={r} className="rel-ring" />
        {drawn.map((rel) => {
          const a = pos.get(rel.from_entity_id)!;
          const b = pos.get(rel.to_entity_id)!;
          // Stop the line short of each name plate.
          const dx = b.x - a.x;
          const dy = b.y - a.y;
          const len = Math.hypot(dx, dy) || 1;
          const pad = 26;
          const x1 = a.x + (dx / len) * pad;
          const y1 = a.y + (dy / len) * pad;
          const x2 = b.x - (dx / len) * pad;
          const y2 = b.y - (dy / len) * pad;
          // Bow the line toward the centre so labels of opposite pairs do not collide.
          const mx = (x1 + x2) / 2 + (cx - (x1 + x2) / 2) * 0.18;
          const my = (y1 + y2) / 2 + (cy - (y1 + y2) / 2) * 0.18;
          return (
            <g key={rel.id} className={`rel-edge rel-${rel.status}`}>
              <path d={`M${x1},${y1} Q${mx},${my} ${x2},${y2}`} markerEnd="url(#rel-arrow)" />
              <text x={mx} y={my - 4} textAnchor="middle" className="rel-label">
                {rel.label}
              </text>
            </g>
          );
        })}
        {people.map((p) => {
          const q = pos.get(p.id)!;
          const right = Math.cos(q.a) > 0.2;
          const left = Math.cos(q.a) < -0.2;
          return (
            <g key={p.id} className={`rel-node rel-${p.status}`}>
              <circle cx={q.x} cy={q.y} r={7} />
              <text
                x={q.x + (right ? 14 : left ? -14 : 0)}
                y={q.y + (right || left ? 5 : Math.sin(q.a) > 0 ? 26 : -16)}
                textAnchor={right ? "start" : left ? "end" : "middle"}
                className="rel-name"
              >
                {p.name}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="muted">Arrows point from a character to the one they are related to.</figcaption>
    </figure>
  );
}
