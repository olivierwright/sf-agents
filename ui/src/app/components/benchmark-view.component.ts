import {
  Component,
  Input,
  inject,
  signal,
  ChangeDetectionStrategy,
  OnChanges,
  SimpleChanges,
} from '@angular/core';
import { ApiService, BenchmarkRun, RunStatus } from '../services/api.service';

interface BenchmarkResult {
  strategy: string;
  run_id: string;
  status: 'pending' | 'running' | 'done' | 'error';
  steps?: number;
  confidence?: number;
  verified?: boolean;
  elapsed_ms?: number;
  error?: string | null;
}

@Component({
  selector: 'app-benchmark-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (results().length > 0) {
      <section class="benchmark">
        <h3 class="benchmark-title">Strategy Comparison</h3>
        <div
          class="benchmark-grid"
          [style.grid-template-columns]="'repeat(' + results().length + ', 1fr)'"
        >
          @for (r of results(); track r.strategy) {
            <div
              class="strategy-col"
              [class.done]="r.status === 'done'"
              [class.error]="r.status === 'error'"
            >
              <div class="strategy-header">
                <span class="strategy-name">{{ r.strategy }}</span>
                <span
                  class="strategy-status badge"
                  [class.badge-accent]="r.status === 'done'"
                  [class.badge-prim]="r.status === 'running' || r.status === 'pending'"
                  >{{ r.status }}</span
                >
              </div>
              @if (r.status === 'done') {
                <div class="strategy-metrics">
                  @if (r.steps != null) {
                    <div class="metric">
                      <span class="metric-label">Plan steps</span>
                      <span class="metric-value mono">{{ r.steps }}</span>
                    </div>
                  }
                  @if (r.elapsed_ms != null) {
                    <div class="metric">
                      <span class="metric-label">Duration</span>
                      <span class="metric-value mono">{{ formatMs(r.elapsed_ms) }}</span>
                    </div>
                  }
                  @if (r.confidence != null) {
                    <div class="metric">
                      <span class="metric-label">Avg confidence</span>
                      <span class="metric-value mono">{{ (r.confidence * 100).toFixed(0) }}%</span>
                    </div>
                  }
                  @if (r.verified != null) {
                    <div class="metric">
                      <span class="metric-label">Citations verified</span>
                      <span
                        class="metric-value"
                        [class.text-success]="r.verified"
                        [class.text-danger]="!r.verified"
                      >
                        {{ r.verified ? 'Pass' : 'Fail' }}
                      </span>
                    </div>
                  }
                </div>
              } @else if (r.status === 'error') {
                <p class="strategy-error">{{ r.error ?? 'Run failed' }}</p>
              } @else {
                <p class="strategy-pending">Running…</p>
              }
            </div>
          }
        </div>
      </section>
    }
  `,
  styles: [
    `
      .benchmark {
        padding: var(--sp-6) var(--sp-8);
        border-top: 1px solid var(--border);
        animation: fadeInUp var(--duration-md) var(--ease-out);
      }
      .benchmark-title {
        font-size: 1rem;
        font-weight: 500;
        margin-bottom: var(--sp-4);
      }
      .benchmark-grid {
        display: grid;
        gap: var(--sp-4);
      }
      .strategy-col {
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        padding: var(--sp-4);
        background: var(--bg-surface);
        transition: border-color var(--duration-fast) var(--ease-out);
      }
      .strategy-col.done {
        border-color: rgba(27, 111, 107, 0.3);
      }
      .strategy-col.error {
        border-color: rgba(198, 40, 40, 0.3);
      }
      .strategy-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: var(--sp-3);
      }
      .strategy-name {
        font-weight: 600;
        font-size: 0.875rem;
      }
      .strategy-metrics {
        display: flex;
        flex-direction: column;
        gap: var(--sp-2);
      }
      .metric {
        display: flex;
        justify-content: space-between;
        font-size: 0.8125rem;
      }
      .metric-label {
        color: var(--text-secondary);
      }
      .metric-value {
        font-weight: 500;
      }
      .strategy-pending,
      .strategy-error {
        font-size: 0.8125rem;
        color: var(--text-muted);
      }
      .strategy-error {
        color: var(--color-danger);
      }
      .text-success {
        color: var(--color-success, #2e7d32);
      }
      .text-danger {
        color: var(--color-danger, #c62828);
      }
    `,
  ],
})
export class BenchmarkViewComponent implements OnChanges {
  @Input() runs: BenchmarkRun[] = [];
  private api = inject(ApiService);
  readonly results = signal<BenchmarkResult[]>([]);
  private pollIntervals: ReturnType<typeof setInterval>[] = [];

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['runs'] && this.runs.length > 0) {
      this.clearPollers();
      this.results.set(
        this.runs.map((r) => ({ strategy: r.strategy, run_id: r.run_id, status: 'running' })),
      );
      this.startPolling();
    }
  }

  ngOnDestroy(): void {
    this.clearPollers();
  }

  private startPolling(): void {
    this.runs.forEach((run) => {
      const iv = setInterval(() => this.pollResult(run), 2000);
      this.pollIntervals.push(iv);
    });
  }

  private pollResult(run: BenchmarkRun): void {
    this.api.getResult(run.run_id).subscribe({
      next: (status: RunStatus) => {
        if (status.status === 'done' || status.status === 'error') {
          this.results.update((list) =>
            list.map((r) =>
              r.run_id === run.run_id ? this.toResult(run.strategy, run.run_id, status) : r,
            ),
          );
          this.clearPoller(run.run_id);
        }
      },
      error: () => {
        /* 425 means still running — ignore */
      },
    });
  }

  private toResult(strategy: string, run_id: string, status: RunStatus): BenchmarkResult {
    const result = status.result;
    if (!result) return { strategy, run_id, status: status.status as any, error: status.error };
    const plan = result['plan'] as { steps?: unknown[] } | undefined;
    const verification = result['verification'] as { ok?: boolean } | undefined;
    return {
      strategy,
      run_id,
      status: status.status as any,
      steps: plan?.steps?.length,
      verified: verification?.ok,
      confidence: undefined,
      elapsed_ms: undefined,
      error: status.error,
    };
  }

  private clearPoller(runId: string): void {
    // Mark as done — the interval will stop when all are cleared
  }

  private clearPollers(): void {
    this.pollIntervals.forEach((iv) => clearInterval(iv));
    this.pollIntervals = [];
  }

  formatMs(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }
}
