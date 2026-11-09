// App — providers + router. Order: Router (so guards can use location) → Auth → Toast → routes.
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { BrowserRouter } from 'react-router';
import { AuthProvider } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';
import { NativeBridge } from '@/native/NativeBridge';
import { AppRoutes } from '@/routes';

interface BoundaryState {
  error: unknown;
}

/** Last-resort boundary: a failed lazy chunk (network / redeploy) or an unexpected render error. */
class AppErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  override state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: unknown): BoundaryState {
    return { error };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    if (import.meta.env.DEV) console.error('Unhandled render error', error, info.componentStack);
  }

  override render() {
    if (this.state.error === null) return this.props.children;
    const message = this.state.error instanceof Error ? this.state.error.message : '';
    const isChunk = /import|fetch|chunk|module/i.test(message);
    return (
      <div className="page page--narrow" role="alert">
        <h1 className="page__title">{isChunk ? zh.errors.network : zh.errors.server}</h1>
        <button type="button" className="btn btn--primary btn--md" onClick={() => window.location.reload()}>
          <span className="btn__label">{zh.common.retry}</span>
        </button>
      </div>
    );
  }
}

export default function App() {
  return (
    <AppErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <ToastProvider>
            <NativeBridge />
            <AppRoutes />
          </ToastProvider>
        </AuthProvider>
      </BrowserRouter>
    </AppErrorBoundary>
  );
}
