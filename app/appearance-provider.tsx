'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { appearanceKey, applyAppearance, defaultAppearance, parseAppearance, readAppearance, saveAppearance } from './appearance';
import type { Appearance } from './appearance';

type AppearanceContextValue = {
  appearance: Appearance;
  changeAppearance: (value: Appearance) => void;
  preferenceNotice: string;
};
const AppearanceContext = createContext<AppearanceContextValue | null>(null);

export default function AppearanceProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearance] = useState<Appearance>(defaultAppearance);
  const [preferenceNotice, setPreferenceNotice] = useState('');

  useEffect(() => {
    // The head bootstrap already applies colors before paint; hydrate React controls
    // without replacing the root attributes with the default server snapshot.
    const timer = window.setTimeout(() => {
      let value = defaultAppearance;
      try { value = readAppearance(window.localStorage); } catch { /* Storage may be disabled. */ }
      setAppearance(value);
      applyAppearance(document.documentElement, value);
    }, 0);
    const syncOtherTab = (event: StorageEvent) => {
      if (event.key !== appearanceKey && event.key !== null) return;
      const value = parseAppearance(event.newValue);
      setAppearance(value);
      applyAppearance(document.documentElement, value);
      setPreferenceNotice('已同步此浏览器其他页面的外观设置。');
    };
    window.addEventListener('storage', syncOtherTab);
    return () => { window.clearTimeout(timer); window.removeEventListener('storage', syncOtherTab); };
  }, []);

  const changeAppearance = (value: Appearance) => {
    setAppearance(value);
    applyAppearance(document.documentElement, value);
    let saved = false;
    try { saved = saveAppearance(window.localStorage, value); } catch { /* Storage may be disabled. */ }
    setPreferenceNotice(saved ? '已保存，所有工作页面将使用此外观。' : '已应用外观；浏览器禁止保存，重新加载后将恢复默认。');
  };

  return <AppearanceContext.Provider value={{ appearance, changeAppearance, preferenceNotice }}>{children}</AppearanceContext.Provider>;
}

export function useWorkspaceAppearance() {
  const context = useContext(AppearanceContext);
  if (!context) throw new Error('外观设置必须在AppearanceProvider中使用');
  return context;
}
