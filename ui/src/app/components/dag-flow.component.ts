import { Component, Input, computed, inject, ChangeDetectionStrategy } from '@angular/core';
import { DagStep } from '../services/run-state.service';
import { RunStateService } from '../services/run-state.service';

interface WaveGroup {
  depth: number;
  steps: DagStep[];
}

@Component({
  selector: 'app-dag-flow',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="dag-flow">
      @for (wave of waves(); track wave.depth; let last = $last) {
        <div class="dag-wave">
          <div class="wave-nodes">
            @for (step of wave.steps; track step.step_id) {
              <div
                class="dag-node"
                [class]="
                  'dag-node dag-node-' +
                  primType(step.primitive) +
                  ' status-' +
                  stepStatus(step.step_id)
                "
                [title]="step.primitive + ' [' + step.step_id + ']'"
              >
                <span class="node-type-dot" [class]="'dot-' + primType(step.primitive)"></span>
                <span class="node-prim">{{ shortPrim(step.primitive) }}</span>
                <span class="node-id mono">{{ step.step_id }}</span>
                @if (stepStatus(step.step_id) === 'running') {
                  <span class="node-spinner">⟳</span>
                }
                @if (stepStatus(step.step_id) === 'done') {
                  <span class="node-done">✓</span>
                }
              </div>
            }
          </div>
          @if (!last) {
            <div class="dag-arrow">→</div>
          }
        </div>
      }
    </div>
  `,
  styles: [
    `
      .dag-flow {
        display: flex;
        align-items: flex-start;
        gap: var(--sp-1);
        flex-wrap: wrap;
        padding: var(--sp-3);
        background: rgba(0, 0, 0, 0.03);
        border-radius: var(--radius-md);
        border: 1px solid var(--border);
        margin-top: var(--sp-2);
      }
      .dag-wave {
        display: flex;
        align-items: center;
        gap: var(--sp-1);
      }
      .wave-nodes {
        display: flex;
        flex-direction: column;
        gap: var(--sp-1);
      }
      .dag-node {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 3px var(--sp-2);
        border-radius: var(--radius-sm);
        border: 1px solid var(--border);
        background: var(--bg-surface);
        font-size: 0.5625rem;
        cursor: default;
        transition: all var(--duration-fast) var(--ease-out);
        min-width: 90px;
      }
      /* type colors */
      .dag-node-connector {
        border-color: rgba(45, 90, 142, 0.3);
      }
      .dag-node-extractor {
        border-color: rgba(27, 111, 107, 0.3);
      }
      .dag-node-analyzer {
        border-color: rgba(123, 94, 167, 0.3);
      }
      .dag-node-validator {
        border-color: rgba(46, 125, 50, 0.3);
      }
      /* status */
      .status-running {
        animation: dagPulse 1s ease-in-out infinite;
      }
      .status-done {
        background: rgba(46, 125, 50, 0.06) !important;
      }
      .status-error {
        border-color: rgba(198, 40, 40, 0.4) !important;
        background: rgba(198, 40, 40, 0.04) !important;
      }
      @keyframes dagPulse {
        0%,
        100% {
          opacity: 1;
        }
        50% {
          opacity: 0.6;
        }
      }

      .node-type-dot {
        width: 5px;
        height: 5px;
        border-radius: 50%;
        flex-shrink: 0;
      }
      .dot-connector {
        background: var(--color-prim);
      }
      .dot-extractor {
        background: var(--accent);
      }
      .dot-analyzer {
        background: var(--color-agent);
      }
      .dot-validator {
        background: var(--color-success);
      }

      .node-prim {
        color: var(--text-secondary);
        white-space: nowrap;
      }
      .node-id {
        color: var(--text-muted);
        font-size: 0.5rem;
      }
      .node-spinner {
        color: var(--color-prim);
        font-size: 0.75rem;
        animation: spin 1s linear infinite;
      }
      .node-done {
        color: var(--color-success);
        font-size: 0.5625rem;
      }
      @keyframes spin {
        from {
          transform: rotate(0deg);
        }
        to {
          transform: rotate(360deg);
        }
      }

      .dag-arrow {
        color: var(--text-muted);
        font-size: 0.875rem;
        padding: 0 2px;
        align-self: center;
      }
    `,
  ],
})
export class DagFlowComponent {
  @Input() steps: DagStep[] = [];
  protected state = inject(RunStateService);

  readonly waves = computed<WaveGroup[]>(() => {
    const steps = this.steps;
    if (!steps.length) return [];

    const deps: Record<string, Set<string>> = {};
    for (const s of steps) deps[s.step_id] = new Set(s.depends_on ?? []);

    const depth: Record<string, number> = {};
    const calc = (sid: string): number => {
      if (sid in depth) return depth[sid];
      const d = deps[sid];
      depth[sid] = d.size === 0 ? 0 : 1 + Math.max(...[...d].map(calc));
      return depth[sid];
    };
    for (const s of steps) calc(s.step_id);

    const groups: Record<number, DagStep[]> = {};
    for (const s of steps) {
      const d = depth[s.step_id];
      if (!groups[d]) groups[d] = [];
      groups[d].push(s);
    }
    return Object.entries(groups)
      .sort(([a], [b]) => +a - +b)
      .map(([d, ss]) => ({ depth: +d, steps: ss }));
  });

  stepStatus(stepId: string): 'pending' | 'running' | 'done' | 'error' {
    const s = this.state.steps().find((st) => st.step_id === stepId);
    return s?.status ?? 'pending';
  }

  primType(name: string): string {
    return name.split('.')[0] ?? 'connector';
  }

  shortPrim(name: string): string {
    const parts = name.split('.');
    return parts[parts.length - 1] ?? name;
  }
}
