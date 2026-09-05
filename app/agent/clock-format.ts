/** Uses the device time zone unless a specific zone is supplied (e.g. in tests). */
export function formatClock(value: Date, timeZone?: string) {
  return {
    time: new Intl.DateTimeFormat('zh-CN', {
      timeZone, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
    }).format(value),
    date: new Intl.DateTimeFormat('zh-CN', {
      timeZone, year: 'numeric', month: 'long', day: 'numeric', weekday: 'long',
    }).format(value),
  };
}
