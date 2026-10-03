import { CheckCircleIcon, CloseIcon } from './NavIcons';
import './Toast.css';

/**
 * Bottom-centre status message; pair with the useToast hook.
 *
 * `tone="success"` adds a tick, and `onClose` a close button -- for the
 * messages that carry something to read (what was generated, what to do next)
 * and so stay up long enough to want dismissing. Either way it floats above
 * the page, so showing it never moves anything.
 */
const Toast = ({ message, tone, onClose, closeLabel }) =>
  message ? (
    <div className={`app-toast ${tone ? `is-${tone}` : ''}`} role="status">
      {tone === 'success' && <CheckCircleIcon className="app-toast-icon" />}
      <span className="app-toast-text">{message}</span>
      {onClose && (
        <button
          type="button"
          className="app-toast-close"
          onClick={onClose}
          aria-label={closeLabel}
          title={closeLabel}
        >
          <CloseIcon className="" />
        </button>
      )}
    </div>
  ) : null;

export default Toast;
