import { Injectable, signal } from '@angular/core';
import { Observable } from 'rxjs';

export interface RunEventData {
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export type SseState = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

@Injectable({ providedIn: 'root' })
export class SseService {
  /** Reactive connection state. */
  readonly state = signal<SseState>('idle');

  private maxRetries = 6;
  private retryDelay = 1500;

  /**
   * Opens an SSE stream with automatic reconnect on transient failures.
   * Completes on run_finished / run_error. Errors after maxRetries exhausted.
   */
  stream(url: string): Observable<RunEventData> {
    return new Observable<RunEventData>((subscriber) => {
      let retries = 0;
      let es: EventSource | null = null;
      let closed = false;

      const connect = () => {
        if (closed) return;
        this.state.set('connecting');
        es = new EventSource(url);

        es.onopen = () => {
          this.state.set('open');
          retries = 0; // reset on successful connect
        };

        es.onmessage = (ev: MessageEvent) => {
          try {
            const data = JSON.parse(ev.data) as RunEventData;
            subscriber.next(data);
            if (data.type === 'run_finished' || data.type === 'run_error') {
              cleanup();
              this.state.set('closed');
              subscriber.complete();
            }
          } catch {
            // skip malformed frames
          }
        };

        es.onerror = () => {
          es?.close();
          if (closed) return;

          if (retries < this.maxRetries) {
            retries++;
            this.state.set('connecting');
            setTimeout(connect, this.retryDelay * retries);
          } else {
            this.state.set('error');
            subscriber.error(new Error('SSE connection failed after retries'));
          }
        };
      };

      const cleanup = () => {
        closed = true;
        es?.close();
        es = null;
      };

      connect();
      return cleanup;
    });
  }
}
