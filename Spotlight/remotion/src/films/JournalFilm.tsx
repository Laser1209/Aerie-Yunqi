import {Easing, interpolate} from 'remotion';
import {
  CornerFrame,
  GlassPlane,
  ParticleField,
  SceneBackdrop,
  loopValue,
  useLoop,
} from '../shared/scene';

const palette = {
  background: '#020806',
  deep: '#081a15',
  primary: '#61d6aa',
  secondary: '#a4d6c3',
  highlight: '#e1fff2',
};

const AbstractDocument = ({
  x,
  y,
  width,
  height,
  offset,
  opacity,
}: {
  x: number;
  y: number;
  width: number;
  height: number;
  offset: number;
  opacity: number;
}) => {
  const {phase} = useLoop();
  const floatY = loopValue(phase, -18, 18, offset);
  const tilt = loopValue(phase, -2.6, 2.6, offset + 1.3);
  const widths = [0.64, 0.84, 0.47, 0.72, 0.58, 0.79, 0.38];

  return (
    <GlassPlane
      tint={palette.primary}
      style={{
        width,
        height,
        left: x,
        top: y,
        borderRadius: 24,
        opacity,
        transform: `translateY(${floatY}px) rotate(${tilt}deg)`,
      }}
    >
      <div style={{padding: 25}}>
        <div style={{display: 'flex', gap: 8, marginBottom: 25}}>
          {[0, 1, 2].map((dot) => (
            <div key={dot} style={{width: 7, height: 7, borderRadius: '50%', background: dot === 0 ? '#bffff0' : 'rgba(255,255,255,0.2)'}} />
          ))}
        </div>
        {widths.map((lineWidth, index) => (
          <div
            key={index}
            style={{
              width: `${lineWidth * 100}%`,
              height: index === 0 ? 11 : 6,
              marginBottom: 13,
              borderRadius: 5,
              background: index === 0 ? 'rgba(213,255,241,0.32)' : index % 3 === 0 ? 'rgba(100,230,187,0.22)' : 'rgba(255,255,255,0.1)',
            }}
          />
        ))}
        <div
          style={{
            position: 'absolute',
            right: 22,
            bottom: 22,
            width: 34,
            height: 34,
            borderRadius: 11,
            border: '1px solid rgba(149,255,219,0.22)',
            background: 'rgba(90,225,179,0.08)',
          }}
        />
      </div>
    </GlassPlane>
  );
};

const VersionTimeline = () => {
  const {frame, durationInFrames, phase} = useLoop();
  const progress = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.linear,
  });
  const nodes = [650, 890, 1130, 1370, 1610];

  return (
    <svg width="1920" height="1080" style={{position: 'absolute', inset: 0}}>
      <defs>
        <linearGradient id="journal-line" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#67e1b4" stopOpacity="0" />
          <stop offset="0.22" stopColor="#67e1b4" stopOpacity="0.28" />
          <stop offset="0.72" stopColor="#d2ffef" stopOpacity="0.78" />
          <stop offset="1" stopColor="#67e1b4" stopOpacity="0.04" />
        </linearGradient>
        <filter id="journal-glow" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="7" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <path d="M 500 640 C 830 596, 1260 696, 1760 614" fill="none" stroke="#56d4a5" strokeWidth="20" strokeOpacity="0.025" />
      <path
        d="M 500 640 C 830 596, 1260 696, 1760 614"
        fill="none"
        stroke="url(#journal-line)"
        strokeWidth="2"
        strokeDasharray="48 72"
        strokeDashoffset={-120 * progress}
        filter="url(#journal-glow)"
      />
      {nodes.map((x, index) => {
        const y = 630 + Math.sin(index * 1.4) * 22;
        const pulse = loopValue(phase, 0.48, 1, index * 1.17);
        const radius = loopValue(phase, 17, 28, index * 1.17);
        return (
          <g key={x} opacity={pulse}>
            <line x1={x} y1={y - 80} x2={x} y2={y + 78} stroke="#87e8c4" strokeOpacity="0.12" />
            <circle cx={x} cy={y} r={radius} fill="#62ddb0" opacity="0.035" />
            <circle cx={x} cy={y} r="8" fill="#caffec" filter="url(#journal-glow)" />
            <circle cx={x} cy={y} r="16" fill="none" stroke="#71e4b9" strokeOpacity="0.36" />
          </g>
        );
      })}
      {Array.from({length: 28}, (_, index) => {
        const offset = (index * 0.137) % 1;
        const orbit = phase + index * 0.77;
        const x = 640 + offset * 1100 + Math.cos(orbit) * (16 + (index % 4) * 8);
        const y = 180 + ((index * 193) % 720) + Math.sin(orbit) * 22;
        const length = 12 + (index % 5) * 7;
        return (
          <line
            key={index}
            x1={x}
            y1={y}
            x2={x + length}
            y2={y + (index % 2 === 0 ? 0 : 3)}
            stroke={index % 4 === 0 ? '#baffdf' : '#6dd8af'}
            strokeWidth={index % 4 === 0 ? 2 : 1}
            strokeOpacity={0.08 + (index % 5) * 0.035}
          />
        );
      })}
    </svg>
  );
};

export const JournalFilm = () => {
  const {phase} = useLoop();
  const cameraX = loopValue(phase, -12, 14, 0.8);

  return (
    <SceneBackdrop palette={palette}>
      <ParticleField color="#9dffd8" count={38} seed={94} />
      <VersionTimeline />
      <div style={{position: 'absolute', inset: 0, transform: `translateX(${cameraX}px)`, perspective: 1500}}>
        <AbstractDocument x={1040} y={190} width={430} height={300} offset={0.4} opacity={0.76} />
        <AbstractDocument x={1415} y={280} width={310} height={240} offset={2.6} opacity={0.48} />
        <AbstractDocument x={850} y={710} width={360} height={250} offset={4.4} opacity={0.4} />
        <AbstractDocument x={1270} y={700} width={470} height={290} offset={5.5} opacity={0.68} />
      </div>
      <CornerFrame color="rgba(140,245,205,0.72)" />
    </SceneBackdrop>
  );
};
