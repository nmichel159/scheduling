import './Toast.css';

/** Bottom-centre status message; pair with the useToast hook. */
const Toast = ({ message }) =>
  message ? (
    <div className="app-toast" role="status">
      {message}
    </div>
  ) : null;

export default Toast;
