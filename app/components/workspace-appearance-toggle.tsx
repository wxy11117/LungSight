'use client';

import { useWorkspaceAppearance } from '../appearance-provider';
import { themes } from '../appearance';
import WorkbenchIcon from './workbench-icon';

export default function WorkspaceAppearanceToggle() {
  const { appearance, changeAppearance } = useWorkspaceAppearance();
  return <div className="wb-theme-switch" role="group" aria-label="工作区外观">{themes.map(theme => <button type="button" key={theme.id} aria-label={`使用${theme.label}外观`} aria-pressed={appearance.theme === theme.id} title={`${theme.label}外观`} onClick={() => changeAppearance({ ...appearance, theme: theme.id })}><WorkbenchIcon name={theme.id === 'dark' ? 'moon' : theme.id === 'eye' ? 'eye' : 'sun'} size={16}/><span>{theme.label}</span></button>)}</div>;
}
