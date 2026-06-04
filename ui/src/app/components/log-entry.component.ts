import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { DagFlowComponent } from './dag-flow.component';
import { DagStep } from '../services/run-state.service';

export interface LogEntry {
  type:
    | 'orchestrator'
    | 'plan'
    | 'step_start'
    | 'step_done'
    | 'review'
    | 'verify'
    | 'complete'
    | 'error';
  timestamp: string;
  stepIndex?: number;
  totalSteps?: number;
  primitive?: string;
  primitiveType?: string;
  confidence?: number;
  durationMs?: number;
  citations?: { source: string; location: string; excerpt: string }[];
  issues?: string[];
  content?: string;
  plan?: DagStep[];
  explanation?: string;
}

@Component({
  selector: 'app-log-entry',
  standalone: true,
  imports: [DagFlowComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="log-entry" [class]="entryClass()">
      <!-- Timestamp + type label -->
      <div class="entry-header">
        <span class="entry-ts mono">{{ entry.timestamp }}</span>
        <span class="entry-type-badge" [class]="'etb-' + entry.type">{{ typeLabel() }}</span>
        @if (entry.stepIndex != null && entry.totalSteps != null) {
          <span class="step-counter mono">{{ entry.stepIndex }}/{{ entry.totalSteps }}</span>
        }
        @if (entry.primitive) {
          <span class="prim-name mono">{{ entry.primitive }}</span>
          <span class="ptype-pill" [class]="'ptype-' + (entry.primitiveType ?? '')">{{
            (entry.primitiveType ?? '').slice(0, 3).toUpperCase()
          }}</span>
        }
        @if (entry.confidence != null) {
          <span class="conf-val" [class]="confClass()">{{ entry.confidence.toFixed(2) }}</span>
        }
        @if (entry.durationMs != null) {
          <span class="dur-val mono">{{ fmtMs(entry.durationMs) }}</span>
        }
      </div>

      <!-- Content line -->
      @if (entry.content) {
        <div class="entry-content">{{ entry.content }}</div>
      }

      <!-- Explanation (plan or orchestrator) -->
      @if (entry.explanation) {
        <div class="entry-explanation">{{ entry.explanation }}</div>
      }

      <!-- DAG flow (plan_ready) -->
      @if (entry.plan && entry.plan.length > 0) {
        <app-dag-flow [steps]="entry.plan" />
      }

      <!-- Citations -->
      @if (entry.citations && entry.citations.length > 0) {
        <div class="citations-list">
          @for (c of entry.citations; track c.location; let last = $last) {
            <div class="citation-row">
              <span class="cite-tree">{{ last ? '└─' : '├─' }}</span>
              <span class="cite-icon">📄</span>
              <span class="cite-source mono">{{ c.source }}</span>
              <span class="cite-loc badge-loc mono">{{ c.location }}</span>
              <span class="cite-excerpt">"{{ truncate(c.excerpt, 80) }}"</span>
            </div>
          }
        </div>
      }

      <!-- Issues/warnings -->
      @if (entry.issues && entry.issues.length > 0) {
        <div class="issues-list">
          @for (issue of entry.issues; track issue) {
            <div class="issue-row">
              <span class="issue-icon">⚠</span>
              <span class="issue-text">{{ issue }}</span>
            </div>
          }
        </div>
      }
    </div>
  `,
  styles: [
    `
      .log-entry {
        padding: var(--sp-2) var(--sp-4);
        border-left: 2px solid transparent;
        animation: slideInEntry 200ms var(--ease-out);
        font-size: 0.8125rem;
      }
      @keyframes slideInEntry {
        from {
          opacity: 0;
          transform: translateX(-4px);
        }
        to {
          opacity: 1;
          transform: translateX(0);
        }
      }
      .log-entry + .log-entry {
        border-top: 1px solid rgba(0, 0, 0, 0.04);
      }

      /* Border colors by type */
      .log-entry.type-orchestrator {
        border-color: var(--accent);
      }
      .log-entry.type-plan {
        border-color: var(--accent);
        background: rgba(27, 111, 107, 0.02);
      }
      .log-entry.type-step_start {
        border-color: var(--color-prim);
      }
      .log-entry.type-step_done {
        border-color: var(--color-success);
      }
      .log-entry.type-review {
        border-color: var(--color-warning);
        background: rgba(230, 81, 0, 0.02);
      }
      .log-entry.type-verify {
        border-color: var(--color-success);
        background: rgba(46, 125, 50, 0.03);
      }
      .log-entry.type-complete {
        border-color: var(--color-success);
        background: rgba(46, 125, 50, 0.05);
      }
      .log-entry.type-error {
        border-color: var(--color-danger);
        background: rgba(198, 40, 40, 0.04);
      }

      .entry-header {
        display: flex;
        align-items: center;
        gap: var(--sp-2);
        flex-wrap: wrap;
      }
      .entry-ts {
        font-size: 0.625rem;
        color: var(--text-muted);
        white-space: nowrap;
      }
      .entry-type-badge {
        font-size: 0.5rem;
        font-family: var(--font-mono);
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        padding: 1px 5px;
        border-radius: var(--radius-sm);
      }
      .etb-orchestrator {
        background: rgba(27, 111, 107, 0.1);
        color: var(--accent);
      }
      .etb-plan {
        background: rgba(27, 111, 107, 0.1);
        color: var(--accent);
      }
      .etb-step_start {
        background: rgba(45, 90, 142, 0.1);
        color: var(--color-prim);
      }
      .etb-step_done {
        background: rgba(46, 125, 50, 0.1);
        color: var(--color-success);
      }
      .etb-review {
        background: rgba(230, 81, 0, 0.1);
        color: var(--color-warning);
      }
      .etb-verify {
        background: rgba(46, 125, 50, 0.1);
        color: var(--color-success);
      }
      .etb-complete {
        background: rgba(46, 125, 50, 0.15);
        color: var(--color-success);
      }
      .etb-error {
        background: rgba(198, 40, 40, 0.1);
        color: var(--color-danger);
      }

      .step-counter {
        font-size: 0.625rem;
        color: var(--text-muted);
      }
      .prim-name {
        font-size: 0.75rem;
        font-weight: 500;
        color: var(--text-primary);
      }
      .ptype-pill {
        font-size: 0.4375rem;
        font-family: var(--font-mono);
        font-weight: 700;
        padding: 1px 3px;
        border-radius: var(--radius-sm);
        color: #fff;
      }
      .ptype-connector {
        background: var(--color-prim);
      }
      .ptype-extractor {
        background: var(--accent);
      }
      .ptype-analyzer {
        background: var(--color-agent);
      }
      .ptype-validator {
        background: var(--color-success);
      }

      .conf-val {
        font-size: 0.75rem;
        font-family: var(--font-mono);
        font-weight: 600;
      }
      .conf-high {
        color: var(--color-success);
      }
      .conf-mid {
        color: var(--color-warning);
      }
      .conf-low {
        color: var(--color-danger);
      }
      .dur-val {
        font-size: 0.625rem;
        color: var(--text-muted);
      }

      .entry-content {
        margin-top: var(--sp-1);
        font-size: 0.75rem;
        color: var(--text-secondary);
        padding-left: var(--sp-6);
      }
      .entry-explanation {
        margin-top: var(--sp-1);
        font-size: 0.6875rem;
        color: var(--text-muted);
        font-style: italic;
        padding-left: var(--sp-6);
      }

      /* Citations */
      .citations-list {
        padding-left: var(--sp-6);
        margin-top: var(--sp-1);
        display: flex;
        flex-direction: column;
        gap: 1px;
      }
      .citation-row {
        display: flex;
        align-items: baseline;
        gap: var(--sp-2);
        font-size: 0.6875rem;
      }
      .cite-tree {
        color: var(--text-muted);
        font-family: var(--font-mono);
        font-size: 0.625rem;
      }
      .cite-icon {
        font-size: 0.625rem;
      }
      .cite-source {
        color: var(--accent);
        font-size: 0.625rem;
      }
      .badge-loc {
        background: rgba(27, 111, 107, 0.08);
        color: var(--accent);
        border-radius: var(--radius-sm);
        padding: 0 4px;
        font-size: 0.5625rem;
      }
      .cite-excerpt {
        color: var(--text-muted);
        font-style: italic;
        font-size: 0.625rem;
      }

      /* Issues */
      .issues-list {
        padding-left: var(--sp-6);
        margin-top: var(--sp-1);
      }
      .issue-row {
        display: flex;
        align-items: baseline;
        gap: var(--sp-2);
        font-size: 0.6875rem;
      }
      .issue-icon {
        color: var(--color-warning);
        font-size: 0.625rem;
      }
      .issue-text {
        color: var(--color-warning);
      }
    `,
  ],
})
export class LogEntryComponent {
  @Input({ required: true }) entry!: LogEntry;

  entryClass(): string {
    return `log-entry type-${this.entry.type}`;
  }

  typeLabel(): string {
    const labels: Record<string, string> = {
      orchestrator: 'ORCHESTRATOR',
      plan: 'PLAN READY',
      step_start: 'STEP START',
      step_done: 'DONE',
      review: 'REVIEW ⚠',
      verify: 'VERIFIED ✓',
      complete: 'COMPLETE ✓',
      error: 'ERROR ✕',
    };
    return labels[this.entry.type] ?? this.entry.type.toUpperCase();
  }

  confClass(): string {
    const c = this.entry.confidence ?? 0;
    if (c >= 0.8) return 'conf-val conf-high';
    if (c >= 0.5) return 'conf-val conf-mid';
    return 'conf-val conf-low';
  }

  fmtMs(ms: number | undefined): string {
    if (ms == null) return '';
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  }

  truncate(s: string, n: number): string {
    return s && s.length > n ? s.slice(0, n) + '…' : (s ?? '');
  }
}
