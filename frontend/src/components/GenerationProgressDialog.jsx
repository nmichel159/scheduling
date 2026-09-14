import { useEffect, useState } from 'react';
import './GenerationProgressDialog.css';

/**
 * Inner body, mounted only while the dialog is open.
 *
 * Splitting it out is what keeps the elapsed counter correct: mounting resets
 * it to zero, so a second generation never inherits the first one's clock and
 * no effect has to write state to clear it.
 */
const GenerationProgressBody = ({ title, body, estimateLabel, elapsedLabel }) => {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    const startedAt = Date.now();
    const timer = setInterval(
      () => setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000)),
      1000
    );
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="generation-progress-overlay">
      <div
        className="generation-progress"
        role="dialog"
        aria-modal="true"
        aria-busy="true"
        aria-live="polite"
      >
        <div className="generation-progress-spinner" aria-hidden="true" />
        <h2 className="generation-progress-title">{title}</h2>
        <p className="generation-progress-body">{body}</p>
        <div className="generation-progress-track" aria-hidden="true">
          <span className="generation-progress-bar" />
        </div>
        <div className="generation-progress-meta">
          {estimateLabel && <span>{estimateLabel}</span>}
          <span>{elapsedLabel(elapsedSeconds)}</span>
        </div>
      </div>
    </div>
  );
};

/**
 * Blocking progress dialog shown while the MILP solver runs.
 *
 * The dialog has no dismiss affordance on purpose: the request is already in
 * flight and the backend cannot cancel it, so an X button would only hide a
 * solve that still overwrites the view when it lands. The owner closes it by
 * flipping `open` once the request settles.
 *
 * Props:
 * - open: whether to render the dialog
 * - title / body: heading and explanatory line
 * - estimateLabel: pre-formatted "estimated time" line, or null to omit it
 * - elapsedLabel: (seconds) => string, called once per second
 */
const GenerationProgressDialog = ({ open, ...bodyProps }) =>
  open ? <GenerationProgressBody {...bodyProps} /> : null;

export default GenerationProgressDialog;
