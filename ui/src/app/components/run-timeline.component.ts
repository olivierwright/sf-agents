import { Component, inject, computed, ChangeDetectionStrategy } from '@angular/core';
import { RunStateService, DagStep } from '../services/run-state.service';
import { PhaseCardComponent } from './phase-card.component';

interface WaveGroup {
  depth: number;
  steps: DagStep[];
}

@Component({
  selector: 'app-run-timeline',
  standalone: true,
  imports: [PhaseCardComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (state.phase() !== 'idle') {
      <section class="timeline">
        <div class="timeline-header">
          <h2>Run Progress</h2>
          <div class="progress-info">
            <span class="progress-text mono">
              {{ state.completedSteps() }}/{{ state.totalSteps() }} steps
            </span>
            <div class="progress-bar">
              <div class="progress-fill" [style.width.%]="state.progress()"></div>
            </div>
          </div>
        </div>

        @if (state.planExplanation()) {
          <p class="plan-explanation">{{ state.planExplanation() }}</p>
        }

        <!-- DAG wave visualization (shown when plan has multiple waves) -->
        @if (dagWaves().length > 1) {
          <div class="dag-view">
            <h3 class="dag-title">Execution Plan</h3>
            <div class="dag-waves">
              @for (wave of dagWaves(); track wave.depth; let i = $index) {
                <div class="dag-wave">
                  <div class="wave-label">Wave {{ wave.depth + 1 }}</div>
                  <div class="wave-nodes">
                    @for (step of wave.steps; track step.step_id) {
                      <div
                        class="dag-node"
                        [class.running]="stepStatus(step.step_id) === 'running'"
                        [class.done]="stepStatus(step.step_id) === 'done'"
                        [class.error]="stepStatus(step.step_id) === 'error'"
                        [title]="step.step_id"
                      >
                        <span class="node-primitive">{{ shortName(step.primitive) }}</span>
                        <span class="node-id mono">{{ step.step_id }}</span>
                      </div>
                    }
                  </div>
                  @if (i < dagWaves().length - 1) {
                    <div class="wave-arrow">→</div>
                  }
                </div>
              }
            </div>
          </div>
        }

        <div class="steps-list">
          @for (step of state.steps(); track step.step_id; let i = $index) {
            <app-phase-card [step]="step" [style.animation-delay.ms]="i * 60" />
          }
        </div>

        @if (state.phase() === 'done') {
          <div class="done-banner">
            <span class="done-icon">✓</span>
            <span>Analysis complete</span>
            <span class="mono text-muted">{{ formatDuration(state.elapsedMs()) }}</span>
          </div>
        }

        @if (state.phase() === 'error') {
          <div class="error-banner">
            <span class="error-icon">✕</span>
            <span>{{ state.error() }}</span>
          </div>
        }
      </section>
    }
  `,
  styles: [
    `
      .timeline {
        padding: var(--sp-6) var(--sp-8);
        animation: fadeInUp var(--duration-slow) var(--ease-out);
      }
      .timeline-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: var(--sp-4);
      }
      .timeline-header h2 {
        font-size: 1.125rem;
      }
      .progress-info {
        display: flex;
        align-items: center;
        gap: var(--sp-3);
      }
      .progress-text {
        font-size: 0.75rem;
        color: var(--text-muted);
      }
      .progress-bar {
        width: 120px;
        height: 4px;
        border-radius: 2px;
        background: var(--border);
        overflow: hidden;
      }
      .progress-fill {
        height: 100%;
        background: var(--accent);
        border-radius: 2px;
        transition: width var(--duration-md) var(--ease-out);
      }
      .plan-explanation {
        color: var(--text-secondary);
        font-size: 0.8125rem;
        font-style: italic;
        margin-bottom: var(--sp-4);
        padding: var(--sp-3) var(--sp-4);
        background: rgba(27, 111, 107, 0.04);
        border-radius: var(--radius-sm);
        border-left: 3px solid var(--accent);
      }

      /* DAG wave view */
      .dag-view {
        margin-bottom: var(--sp-6);
        animation: fadeInUp var(--duration-md) var(--ease-out);
      }
      .dag-title {
        font-size: 0.875rem;
        font-weight: 500;
        margin-bottom: var(--sp-3);
      }
      .dag-waves {
        display: flex;
        align-items: flex-start;
        gap: var(--sp-2);
        overflow-x: auto;
        padding: var(--sp-3);
        background: rgba(27, 111, 107, 0.03);
        border-radius: var(--radius-md);
        border: 1px solid var(--border);
      }
      .dag-wave {
        display: flex;
        align-items: center;
        gap: var(--sp-2);
        flex-shrink: 0;
      }
      .wave-label {
        font-size: 0.625rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-muted);
        writing-mode: horizontal-tb;
        padding: 0 var(--sp-1);
      }
      .wave-nodes {
        display: flex;
        flex-direction: column;
        gap: var(--sp-1);
      }
      .dag-node {
        display: flex;
        flex-direction: column;
        padding: var(--sp-1) var(--sp-2);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        background: var(--bg-surface);
        min-width: 100px;
        transition: all var(--duration-fast) var(--ease-out);
      }
      .dag-node.running {
        border-color: var(--accent);
        background: rgba(27, 111, 107, 0.06);
      }
      .dag-node.done {
        border-color: rgba(46, 125, 50, 0.4);
        background: rgba(46, 125, 50, 0.04);
      }
      .dag-node.error {
        border-color: rgba(198, 40, 40, 0.4);
        background: rgba(198, 40, 40, 0.04);
      }
      .node-primitive {
        font-size: 0.625rem;
        color: var(--accent);
        font-weight: 600;
      }
      .node-id {
        font-size: 0.5625rem;
        color: var(--text-muted);
      }
      .wave-arrow {
        color: var(--border);
        font-size: 1.25rem;
        padding: 0 var(--sp-1);
        align-self: center;
      }

      .steps-list {
        display: flex;
        flex-direction: column;
        gap: var(--sp-3);
      }
      .done-banner,
      .error-banner {
        display: flex;
        align-items: center;
        gap: var(--sp-3);
        padding: var(--sp-4);
        border-radius: var(--radius-md);
        margin-top: var(--sp-4);
        font-weight: 500;
        animation: fadeInUp var(--duration-md) var(--ease-out);
      }
      .done-banner {
        background: rgba(46, 125, 50, 0.06);
        border: 1px solid rgba(46, 125, 50, 0.2);
        color: var(--color-success);
      }
      .done-icon {
        font-size: 1.25rem;
      }
      .error-banner {
        background: rgba(198, 40, 40, 0.06);
        border: 1px solid rgba(198, 40, 40, 0.2);
        color: var(--color-danger);
      }
      .error-icon {
        font-size: 1.25rem;
      }
    `,
  ],
})
export class RunTimelineComponent {
  protected state = inject(RunStateService);

  readonly dagWaves = computed<WaveGroup[]>(() => {
    const dag = this.state.dag();
    if (!dag.length) return [];

    const byId: Record<string, DagStep> = {};
    for (const s of dag) byId[s.step_id] = s;

    // Collect deps: explicit depends_on only (args $from refs aren't in DagStep)
    const deps: Record<string, Set<string>> = {};
    for (const s of dag) {
      deps[s.step_id] = new Set(s.depends_on ?? []);
    }

    const depth: Record<string, number> = {};
    const calcDepth = (sid: string): number => {
      if (sid in depth) return depth[sid];
      const d = deps[sid];
      depth[sid] = d.size === 0 ? 0 : 1 + Math.max(...[...d].map(calcDepth));
      return depth[sid];
    };
    for (const s of dag) calcDepth(s.step_id);

    const groups: Record<number, DagStep[]> = {};
    for (const s of dag) {
      const d = depth[s.step_id];
      if (!groups[d]) groups[d] = [];
      groups[d].push(s);
    }

    return Object.entries(groups)
      .sort(([a], [b]) => +a - +b)
      .map(([d, steps]) => ({ depth: +d, steps }));
  });

  stepStatus(stepId: string): 'pending' | 'running' | 'done' | 'error' {
    const step = this.state.steps().find((s) => s.step_id === stepId);
    return step?.status ?? 'pending';
  }

  shortName(primitive: string): string {
    const parts = primitive.split('.');
    return parts[parts.length - 1] ?? primitive;
  }

  formatDuration(ms: number): string {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }
}
