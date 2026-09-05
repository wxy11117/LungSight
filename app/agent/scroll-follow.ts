type ScrollMetrics = { scrollTop: number; scrollHeight: number; clientHeight: number };

export function nearBottom({ scrollTop, scrollHeight, clientHeight }: ScrollMetrics) {
  return scrollHeight - clientHeight - Math.max(0, scrollTop) <= 24;
}

/** Track reading intent separately from content growth during streamed answers. */
export function createScrollFollower() {
  let following = true;
  let lastTop = 0;
  return {
    get following() { return following; },
    reset() { following = true; lastTop = 0; },
    pause() { following = false; },
    sync(top: number) { lastTop = top; },
    observe(metrics: ScrollMetrics) {
      if (metrics.scrollTop < lastTop - 1) following = false;
      else if (nearBottom(metrics)) following = true;
      lastTop = metrics.scrollTop;
    },
  };
}
