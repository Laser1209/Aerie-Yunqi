import {Easing, interpolate} from 'remotion';
import {
  CornerFrame,
  ParticleField,
  SceneBackdrop,
  loopValue,
  useLoop,
} from '../shared/scene';

const palette = {
  background: '#02070b',
  deep: '#0a1822',
  primary: '#83cef5',
  secondary: '#d1eefb',
  highlight: '#f1fbff',
};

const crystalPoints = [
  [1320, 140],
  [1510, 260],
  [1615, 525],
  [1515, 790],
  [1320, 940],
  [1125, 790],
  [1025, 525],
  [1130, 260],
];

const Crystal = () => {
  const {frame, durationInFrames, phase} = useLoop();
  const rotation = interpolate(frame, [0, durationInFrames], [0, 360], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
    easing: Easing.linear,
  });
  const breathe = loopValue(phase, 0.965, 1.035, 0.5);
  const facetOpacity = loopValue(phase, 0.62, 0.92, 1.7);

  return (
    <svg width="1920" height="1080" style={{position: 'absolute', inset: 0}}>
      <defs>
        <radialGradient id="download-core">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.96" />
          <stop offset="0.18" stopColor="#bceeff" stopOpacity="0.72" />
          <stop offset="0.55" stopColor="#67bde8" stopOpacity="0.14" />
          <stop offset="1" stopColor="#4096c4" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="download-facet-a" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#eefaff" stopOpacity="0.72" />
          <stop offset="0.44" stopColor="#74c5ee" stopOpacity="0.22" />
          <stop offset="1" stopColor="#1f668f" stopOpacity="0.04" />
        </linearGradient>
        <linearGradient id="download-facet-b" x1="1" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#caedff" stopOpacity="0.5" />
          <stop offset="0.62" stopColor="#589fca" stopOpacity="0.12" />
          <stop offset="1" stopColor="#eaffff" stopOpacity="0.38" />
        </linearGradient>
        <linearGradient id="download-beam" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#7ad0fc" stopOpacity="0" />
          <stop offset="0.72" stopColor="#aee7ff" stopOpacity="0.1" />
          <stop offset="1" stopColor="#ecfbff" stopOpacity="0.42" />
        </linearGradient>
        <filter id="download-glow" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="13" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      <g opacity={loopValue(phase, 0.42, 0.72, 0.8)}>
        <path d="M 280 140 L 1320 520 L 280 310 Z" fill="url(#download-beam)" opacity="0.2" />
        <path d="M 510 1010 L 1320 540 L 730 1060 Z" fill="url(#download-beam)" opacity="0.16" />
        <path d="M 1910 80 L 1330 520 L 1910 260 Z" fill="url(#download-beam)" opacity="0.13" />
        <path d="M 1910 1010 L 1330 550 L 1910 860 Z" fill="url(#download-beam)" opacity="0.16" />
      </g>
      <g transform={`translate(1320 540) rotate(${rotation}) scale(${breathe}) translate(-1320 -540)`}>
        {[0, 1, 2].map((ring) => (
          <ellipse
            key={ring}
            cx="1320"
            cy="540"
            rx={310 + ring * 92}
            ry={110 + ring * 30}
            fill="none"
            stroke={ring === 0 ? '#cbefff' : '#6fbde4'}
            strokeWidth={ring === 0 ? 1.4 : 0.7}
            strokeOpacity={0.18 - ring * 0.045}
            strokeDasharray={`${30 + ring * 14} ${64 + ring * 17}`}
          />
        ))}
      </g>
      <g transform={`translate(1320 540) rotate(${-rotation * 0.52}) scale(${breathe}) translate(-1320 -540)`} opacity={facetOpacity}>
        {crystalPoints.map((point, index) => {
          const next = crystalPoints[(index + 1) % crystalPoints.length];
          const center = index % 2 === 0 ? [1320, 515] : [1320, 565];
          return (
            <polygon
              key={index}
              points={`${center[0]},${center[1]} ${point[0]},${point[1]} ${next[0]},${next[1]}`}
              fill={index % 2 === 0 ? 'url(#download-facet-a)' : 'url(#download-facet-b)'}
              stroke={index % 2 === 0 ? '#ccefff' : '#6cb8df'}
              strokeWidth="1"
              strokeOpacity={0.25 + (index % 3) * 0.08}
            />
          );
        })}
        <polygon
          points="1320,140 1510,260 1448,530 1320,515 1188,525 1130,260"
          fill="url(#download-facet-a)"
          stroke="#ddf5ff"
          strokeOpacity="0.32"
        />
        <polygon
          points="1188,525 1320,515 1448,530 1515,790 1320,940 1125,790"
          fill="url(#download-facet-b)"
          stroke="#8bccec"
          strokeOpacity="0.28"
        />
      </g>
      <circle cx="1320" cy="540" r="205" fill="url(#download-core)" opacity={loopValue(phase, 0.2, 0.42, 2.2)} filter="url(#download-glow)" />
      {Array.from({length: 12}, (_, index) => {
        const angle = phase + (index / 12) * Math.PI * 2;
        const radius = 270 + (index % 4) * 76;
        const x = 1320 + Math.cos(angle * (index % 2 === 0 ? 1 : -1)) * radius;
        const y = 540 + Math.sin(angle) * radius * 0.34;
        return (
          <g key={index} opacity={0.2 + (index % 4) * 0.08}>
            <circle cx={x} cy={y} r={2.4 + (index % 3)} fill="#dcf6ff" filter="url(#download-glow)" />
            <line x1={1320} y1={540} x2={x} y2={y} stroke="#8bd4f5" strokeWidth="0.6" strokeOpacity="0.08" />
          </g>
        );
      })}
    </svg>
  );
};

export const DownloadFilm = () => {
  return (
    <SceneBackdrop palette={palette}>
      <ParticleField color="#c8f2ff" count={42} seed={128} />
      <Crystal />
      <CornerFrame color="rgba(189,236,255,0.78)" />
    </SceneBackdrop>
  );
};
