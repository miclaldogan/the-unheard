import type { NarrativePresence } from "../api/narrative";
/** An identity instrument, never a plot of acoustic measurements. */
export function EchoCore({
  presence,
  memories,
}: {
  presence: NarrativePresence;
  memories: number;
}) {
  return (
    <div
      className={`echo-core presence-${presence}`}
      role="img"
      aria-label={`ECHO-0 presence: ${presence}. Abstract identity, not measured sound.`}
    >
      <svg viewBox="0 0 500 500" aria-hidden="true">
        <defs>
          <radialGradient id="core-light">
            <stop stopColor="#3fa7a0" stopOpacity=".16" />
            <stop offset="1" stopColor="#3fa7a0" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="250" cy="250" r="230" fill="url(#core-light)" />
        <g className="core-graticule" fill="none" stroke="currentColor">
          <circle cx="250" cy="250" r="220" />
          <circle cx="250" cy="250" r="202" strokeDasharray="1 8" />
          <path d="M250 14v45 M250 441v45 M14 250h45 M441 250h45 M94 94l22 22 M384 384l22 22 M94 406l22-22 M384 116l22-22" />
        </g>
        <g className="core-orbits" fill="none" stroke="currentColor">
          <ellipse
            cx="250"
            cy="250"
            rx="152"
            ry="58"
            transform="rotate(-34 250 250)"
          />
          <ellipse
            cx="250"
            cy="250"
            rx="152"
            ry="58"
            transform="rotate(34 250 250)"
          />
          <ellipse
            cx="250"
            cy="250"
            rx="152"
            ry="58"
            transform="rotate(90 250 250)"
          />
          <circle cx="250" cy="250" r="89" strokeDasharray="2 6" />
        </g>
        <g className="core-memories">
          {Array.from({ length: Math.min(24, memories) }, (_, i) => {
            const a = i * 2.39996;
            const radius = 105 + (i % 3) * 22;
            return (
              <circle
                key={i}
                cx={250 + Math.cos(a) * radius}
                cy={250 + Math.sin(a) * radius}
                r="3"
              />
            );
          })}
        </g>
        <circle className="core-heart" cx="250" cy="250" r="18" />
        <text x="250" y="358" textAnchor="middle">
          E C H O — 0
        </text>
        <text className="core-coordinate" x="250" y="476" textAnchor="middle">
          ACOUSTIC MEMORY INSTRUMENT
        </text>
      </svg>
    </div>
  );
}
