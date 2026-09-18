import { createContext, useContext, useEffect } from 'react';

/** Shared by WorkplaceProvider and everything that reads the active workplace. */
export const WorkplaceContext = createContext(null);

export function useWorkplace() {
  const ctx = useContext(WorkplaceContext);
  if (!ctx) throw new Error('useWorkplace must be used inside a WorkplaceProvider');
  return ctx;
}

/**
 * Lets the screen on show veto a workplace switch while it has unsaved
 * edits -- the same protection useBlocker gives it against navigation.
 */
export function useWorkplaceSwitchGuard(isDirty) {
  const { registerGuard } = useWorkplace();
  useEffect(() => registerGuard(() => isDirty), [registerGuard, isDirty]);
}
