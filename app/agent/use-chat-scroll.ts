'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { createScrollFollower, nearBottom } from './scroll-follow';

export function useChatScroll(messages: readonly unknown[], conversationId: string | null, ready: boolean) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const follower = useRef(createScrollFollower());
  const previousConversation = useRef(conversationId);
  const hasMessages = useRef(false);
  const frame = useRef<number | null>(null);
  const [showLatest, setShowLatest] = useState(false);

  const scheduleFollow = useCallback(() => {
    if (frame.current !== null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      const element = scrollRef.current;
      if (!element) return;
      if (follower.current.following) {
        element.scrollTo({ top: hasMessages.current ? element.scrollHeight : 0, behavior: 'instant' });
        follower.current.sync(element.scrollTop);
      }
      setShowLatest(hasMessages.current && !nearBottom(element));
    });
  }, []);

  useEffect(() => {
    if (previousConversation.current !== conversationId) {
      previousConversation.current = conversationId;
      follower.current.reset();
    }
    hasMessages.current = messages.length > 0;
    if (ready) scheduleFollow();
  }, [messages, conversationId, ready, scheduleFollow]);

  useEffect(() => {
    const content = contentRef.current;
    const container = scrollRef.current;
    if (!ready || !content || !container) return;
    const observer = new ResizeObserver(scheduleFollow);
    observer.observe(content);
    observer.observe(container);
    return () => observer.disconnect();
  }, [ready, scheduleFollow]);

  useEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = null;
  }, []);

  const onScroll = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;
    follower.current.observe(element);
    setShowLatest(hasMessages.current && !nearBottom(element));
  }, []);

  const pauseFollowing = useCallback(() => { follower.current.pause(); }, []);
  const followLatest = useCallback(() => { follower.current.reset(); scheduleFollow(); }, [scheduleFollow]);

  return { scrollRef, contentRef, onScroll, pauseFollowing, followLatest, showLatest };
}
