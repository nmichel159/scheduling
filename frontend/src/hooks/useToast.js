import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * A short-lived status message: `notify(text)` shows it, and it goes away on
 * its own. A newer message restarts the clock instead of being cut short by
 * the timer of the one before, and the timer is cleared on unmount.
 *
 * Returns [message, notify]; render the message with <Toast />.
 */
export function useToast(duration = 2400) {
  const [message, setMessage] = useState(null);
  const timerRef = useRef(null);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const notify = useCallback(
    (text) => {
      setMessage(text);
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setMessage(null), duration);
    },
    [duration]
  );

  return [message, notify];
}
