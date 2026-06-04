import { Component, input, ChangeDetectionStrategy } from '@angular/core';
import { StepEvent } from '../services/run-state.service';

@Component({
  selector: 'app-phase-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="phase-card" [class.running]="step().status === 'running'" [class.done]="step().status === 'done'">
      <div class="card-header">
        <span class="step-indicator" [class.active]="step().status === 'running'" [class.complete]="step().status === 'done'">
          @if (step().status === 'running') {
            <span class="spinner"></span>
          } @else if (step().status === 'done') {
            <span class="check">✓</span>
          } @else {
            <span class="dot"></span>
          }
        </span>
        <div class="card-info">
          <span class="primitive-name mono">{{ step().primitive }}</span>
          <span class="step-id text-muted">{{ step().step_id }}</span>
        </div>
        @if (step().status === 'done' && step().confidence != null) {
          <div class="confidence-wrap">
            <div class="confidence-bar">
              <div
                class="confidence-fill"
                [style.width.%]="(step().confidence ?? 0) * 100"
                [class.high]="(step().confidence ?? 0) >= 0.8"
                [class.medium]="(step().confidence ?? 0) >= 0.5 && (step().confidence ?? 0) < 0.8"
                [class.low]="(step().confidence ?? 0) < 0.5"
              ></div>
            </div>
            <span class="confidence-val mono">{{ ((step().confidence ?? 0) * 100).toFixed(0) }}%</span>
          </div>
        }
      </div>
      @if (step().status === 'done' && step().duration_ms != null) {
        <div class="card-meta">
          <span class="duration mono text-muted">{{ step().duration_ms }}ms</span>
          @if (step().issues && step().issues!.length > 0) {
            <span class="badge badge-warning">{{ step().issues!.length }} issue{{ step().issues!.length > 1 ? 's' : '' }}</span>
          }
        </div>
      }
    </div>
  `,
  styles: [`
    .phase-card {
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: var(--sp-4);
      background: var(--bg-surface);
      transition: all var(--duration-md) var(--ease-out);
      animation: fadeInUp var(--duration-md) var(--ease-out) both;
    }
    .phase-card.running {
      border-color: var(--accent);
      animation: borderPulse 2s ease-in-out infinite;
    }
    .phase-card.done {
      border-color: var(--color-success);
      border-left: 3px solid var(--color-success);
    }
    .card-header {
      display: flex;
      align-items: center;
      gap: var(--sp-3);
    }
    .step-indicator {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      background: var(--bg-canvas);
      border: 2px solid var(--border);
      flex-shrink: 0;
      transition: all var(--duration-fast);
    }
    .step-indicator.active {
      border-color: var(--accent);
      background: rgba(27,111,107,.08);
    }
    .step-indicator.complete {
      border-color: var(--color-success);
      background: rgba(46,125,50,.08);
    }
    .spinner {
      width: 12px; height: 12px;
      border: 2px solid var(--accent);
      border-top-color: transparent;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    .check { color: var(--color-success); font-size: 0.75rem; font-weight: 700; }
    .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--border-strong); }
    .card-info {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .primitive-name {
      font-weight: 500;
      color: var(--text-primary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .step-id { font-size: 0.6875rem; }
    .confidence-wrap {
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: var(--sp-2);
    }
    .confidence-bar {
      width: 60px;
      height: 4px;
      border-radius: 2px;
      background: var(--border);
      overflow: hidden;
    }
    .confidence-fill {
      height: 100%;
      border-radius: 2px;
      animation: confidenceFill var(--duration-slow) var(--ease-out) both;
    }
    .confidence-fill.high { background: var(--color-success); }
    .confidence-fill.medium { background: var(--color-warning); }
    .confidence-fill.low { background: var(--color-danger); }
    .confidence-val { font-size: 0.6875rem; }
    .card-meta {
      display: flex;
      align-items: center;
      gap: var(--sp-3);
      margin-top: var(--sp-2);
      padding-left: calc(28px + var(--sp-3));
    }
    .duration { font-size: 0.6875rem; }
  `],
})
export class PhaseCardComponent {
  readonly step = input.required<StepEvent>();
}
