'use client';

import { memo, useEffect, useState } from 'react';
import { formatClock } from './clock-format';
import './workspace-clock.css';

// Keep ticking state in this leaf so conversations and message lists do not
// re-render every second. The initial placeholder also keeps SSR hydration stable.
const WorkspaceClock = memo(function WorkspaceClock() {
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const update = () => setNow(new Date());
    const frame = window.requestAnimationFrame(update);
    const interval = window.setInterval(update, 1000);
    // Always read the actual clock, including after sleep/background throttling.
    document.addEventListener('visibilitychange', update);
    window.addEventListener('focus', update);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', update);
      window.removeEventListener('focus', update);
    };
  }, []);

  const display = now ? formatClock(now) : null;
  return <div className="workspace-clock" role="timer" aria-live="off" aria-label="当前本地时间">
    <h1><time dateTime={now?.toISOString()}>{display?.time || '--:--:--'}</time></h1>
    <p><span>{display?.date || '正在读取日期…'}</span><small>本地时间</small></p>
  </div>;
});

export default WorkspaceClock;
