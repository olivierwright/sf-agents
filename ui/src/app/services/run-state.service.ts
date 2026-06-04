import { Injectable, inject, signal, computed } from '@angular/core';
import { Subscription } from 'rxjs';
import { ApiService, RecipeInfo, UseCaseInfo, DealResponse, HealthResponse } from './api.service';
import { SseService, RunEventData } from './sse.service';

export type RunPhase = 'idle' | 'planning' | 'executing' | 'verifying' | 'waiting_for_input' | 'done' | 'error';

export interface DagStep {
  step_id: string;
  primitive: string;
  depends_on: string[];
}

export interface StepEvent {
  step_id: string;
  primitive: string;
  confidence?: number;
  duration_ms?: number;
  citations?: unknown[];
  issues?: string[];
  status: 'running' | 'done' | 'error';
}

@Injectable({ providedIn: 'root' })
export class RunStateService {
  private api = inject(ApiService);
  private sse = inject(SseService);
  private sub: Subscription | null = null;

  // ── Core signals ────────────────────────────────────────────────────────
  readonly health = signal<HealthResponse | null>(null);
  readonly recipes = signal<RecipeInfo[]>([]);
  readonly useCases = signal<UseCaseInfo[]>([]);
  readonly deal = signal<DealResponse | null>(null);

  readonly runId = signal<string | null>(null);
  readonly phase = signal<RunPhase>('idle');
  readonly events = signal<RunEventData[]>([]);
  readonly steps = signal<StepEvent[]>([]);
  readonly dag = signal<DagStep[]>([]);
  readonly planExplanation = signal<string>('');
  readonly totalSteps = signal(0);
  readonly completedSteps = signal(0);
  readonly result = signal<Record<string, unknown> | null>(null);
  readonly error = signal<string | null>(null);
  readonly startedAt = signal<number | null>(null);
  readonly finishedAt = signal<number | null>(null);

  // Active question/strategy (shown in running banner and result header)
  readonly activeQuestion = signal<string>('');
  readonly activeStrategy = signal<string>('thorough');

  // Draft question — shared between sidebar (pre-fill) and terminal (input)
  readonly questionDraft = signal<string>('');
  readonly strategyDraft = signal<string>('thorough');

  // Human-in-the-loop clarification state
  readonly pendingClarification = signal<{ step_id: string; question: string; issues: string[]; confidence: number } | null>(null);

  // ── Derived ─────────────────────────────────────────────────────────────
  readonly progress = computed(() => {
    const total = this.totalSteps();
    if (total === 0) return 0;
    return Math.round((this.completedSteps() / total) * 100);
  });

  readonly elapsedMs = computed(() => {
    const start = this.startedAt();
    const end = this.finishedAt();
    if (!start) return 0;
    return (end ?? Date.now()) - start;
  });

  readonly isRunning = computed(() => {
    const p = this.phase();
    return p === 'planning' || p === 'executing' || p === 'verifying' || p === 'waiting_for_input';
  });

  // ── Bootstrap ───────────────────────────────────────────────────────────
  loadInitialData(): void {
    this.api.health().subscribe((h) => this.health.set(h));
    this.api.recipes().subscribe((r) => this.recipes.set(r));
    this.api.useCases().subscribe((uc) => this.useCases.set(uc));
    this.api.deal().subscribe((d) => this.deal.set(d));
  }

  // ── Run lifecycle ───────────────────────────────────────────────────────
  startRun(recipe: string): void {
    const label = this.recipes().find((r) => r.id === recipe)?.label ?? recipe;
    this._launch(label, 'thorough', () => this.api.startRun(recipe));
  }

  startQuestion(question: string, strategy: string): void {
    this._launch(question, strategy, () => this.api.startQuestion(question, strategy));
  }

  private _launch(
    question: string,
    strategy: string,
    apiCall: () => ReturnType<ApiService['startRun']>,
  ): void {
    this.reset();
    this.phase.set('planning');
    this.startedAt.set(Date.now());
    this.activeQuestion.set(question);
    this.activeStrategy.set(strategy);

    apiCall().subscribe({
      next: (resp) => {
        this.runId.set(resp.run_id);
        this.subscribeToStream(resp.stream_url);
      },
      error: (err) => {
        this.phase.set('error');
        this.error.set(err?.message ?? 'Failed to start run');
      },
    });
  }

  private subscribeToStream(url: string): void {
    this.sub?.unsubscribe();
    this.sub = this.sse.stream(url).subscribe({
      next: (ev) => this.handleEvent(ev),
      error: (err) => {
        this.phase.set('error');
        this.error.set(err?.message ?? 'Stream connection lost');
      },
      complete: () => {
        // Stream closed without an explicit run_finished/run_error event.
        // Poll the result endpoint once to resolve the final state.
        const id = this.runId();
        if (!id || this.phase() === 'done' || this.phase() === 'error') return;
        this.api.getResult(id).subscribe({
          next: (status) => {
            if (status.status === 'error') {
              this.phase.set('error');
              this.error.set(status.error ?? 'Run failed');
              this.finishedAt.set(Date.now());
            } else if (status.status === 'done' && status.result) {
              this.phase.set('done');
              this.result.set(status.result as Record<string, unknown>);
              this.finishedAt.set(Date.now());
            }
          },
          error: () => {
            if (this.phase() !== 'done') {
              this.phase.set('error');
              this.error.set('Run status unavailable');
            }
          },
        });
      },
    });
  }

  private handleEvent(ev: RunEventData): void {
    this.events.update((list) => [...list, ev]);

    switch (ev.type) {
      case 'run_started':
        this.phase.set('planning');
        break;

      case 'plan_ready':
        this.phase.set('executing');
        this.totalSteps.set((ev.payload['step_count'] as number) ?? 0);
        this.planExplanation.set((ev.payload['explanation'] as string) ?? '');
        const steps = ev.payload['steps'] as DagStep[] | undefined;
        if (steps) this.dag.set(steps);
        break;

      case 'step_started': {
        const step: StepEvent = {
          step_id: ev.payload['step_id'] as string,
          primitive: ev.payload['primitive'] as string,
          status: 'running',
        };
        this.steps.update((list) => [...list, step]);
        break;
      }

      case 'step_finished': {
        const stepId = ev.payload['step_id'] as string;
        this.steps.update((list) =>
          list.map((s) =>
            s.step_id === stepId
              ? {
                  ...s,
                  status: 'done' as const,
                  confidence: ev.payload['confidence'] as number | undefined,
                  duration_ms: ev.payload['duration_ms'] as number | undefined,
                  citations: ev.payload['citations'] as unknown[] | undefined,
                  issues: ev.payload['issues'] as string[] | undefined,
                }
              : s,
          ),
        );
        this.completedSteps.update((n) => n + 1);
        break;
      }

      case 'human_clarification_needed':
        this.phase.set('waiting_for_input');
        this.pendingClarification.set({
          step_id: ev.payload['step_id'] as string,
          question: ev.payload['question'] as string,
          issues: (ev.payload['issues'] as string[]) ?? [],
          confidence: ev.payload['confidence'] as number,
        });
        break;

      case 'verification_done':
        this.phase.set('verifying');
        break;

      case 'run_finished':
        this.phase.set('done');
        this.finishedAt.set(Date.now());
        // run_finished payload is thin ({step_count, review_queue_size, final_step_id}).
        // Fetch the full result (answer, comparisons, citations, verification, etc.)
        // from the REST endpoint. Store the thin payload as a fallback in case the
        // fetch fails.
        this.result.set(ev.payload as Record<string, unknown>);
        {
          const runId = this.runId();
          if (runId) {
            this.api.getResult(runId).subscribe({
              next: (status) => {
                if (status.result) this.result.set(status.result as Record<string, unknown>);
              },
              error: () => { /* keep thin payload already set */ },
            });
          }
        }
        break;

      case 'run_error':
        this.phase.set('error');
        this.finishedAt.set(Date.now());
        this.error.set((ev.payload['message'] as string) ?? 'Unknown error');
        break;
    }
  }

  submitClarification(answer: string): void {
    const id = this.runId();
    if (!id) return;
    this.api.clarify(id, answer).subscribe({
      next: () => {
        this.pendingClarification.set(null);
        this.phase.set('executing');
      },
      error: (err) => {
        this.error.set(err?.message ?? 'Failed to submit clarification');
      },
    });
  }

  reset(): void {
    this.sub?.unsubscribe();
    this.sub = null;
    this.runId.set(null);
    this.phase.set('idle');
    this.events.set([]);
    this.steps.set([]);
    this.dag.set([]);
    this.planExplanation.set('');
    this.totalSteps.set(0);
    this.completedSteps.set(0);
    this.result.set(null);
    this.error.set(null);
    this.startedAt.set(null);
    this.finishedAt.set(null);
    this.pendingClarification.set(null);
  }
}
