export type Appearance = { theme: 'dark' | 'light' | 'eye'; accent: 'classic' | 'rainbow' | 'aurora' | 'sunset' };
export const appearanceKey = 'lungsight.workspace-appearance.v1';
export const defaultAppearance: Appearance = { theme: 'dark', accent: 'classic' };
export const themes = [{ id: 'light', label: '亮色' }, { id: 'dark', label: '夜间' }, { id: 'eye', label: '护眼' }] as const;
export const accents = [
  { id: 'classic', label: '经典', detail: '青蓝 · 默认' },
  { id: 'rainbow', label: '彩虹', detail: '多彩渐变' },
  { id: 'aurora', label: '极光', detail: '紫蓝冷色' },
  { id: 'sunset', label: '落日', detail: '橙粉暖色' },
] as const;

export function parseAppearance(raw: string | null): Appearance {
  try {
    const value = JSON.parse(raw || 'null');
    if (value && themes.some((item) => item.id === value.theme) && accents.some((item) => item.id === value.accent)) {
      return { theme: value.theme, accent: value.accent };
    }
  } catch { /* Old, invalid or missing device settings use the original default. */ }
  return { ...defaultAppearance };
}

export function applyAppearance(root: { dataset: { theme?: string; accent?: string } }, value: Appearance) {
  root.dataset.theme = value.theme;
  root.dataset.accent = value.accent;
}

export function readAppearance(storage: Pick<Storage, 'getItem'>): Appearance {
  try { return parseAppearance(storage.getItem(appearanceKey)); }
  catch { return { ...defaultAppearance }; }
}

export function saveAppearance(storage: Pick<Storage, 'setItem'>, value: Appearance): boolean {
  try { storage.setItem(appearanceKey, JSON.stringify(value)); return true; }
  catch { return false; }
}

// Runs in the document head before page content is painted. Values are allowlisted;
// this embeds no user-provided script or account information.
export const appearanceBootstrap = `(function(){
  var theme='dark',accent='classic';
  try {
    var value=JSON.parse(localStorage.getItem(${JSON.stringify(appearanceKey)})||'null');
    if(value&&${JSON.stringify(themes.map((item) => item.id))}.includes(value.theme)&&${JSON.stringify(accents.map((item) => item.id))}.includes(value.accent)){
      theme=value.theme;accent=value.accent;
    }
  } catch(e) {}
  document.documentElement.dataset.theme=theme;
  document.documentElement.dataset.accent=accent;
})();`;
