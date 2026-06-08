import {
  Component,
  inject,
  signal,
  computed,
  ChangeDetectionStrategy,
  ViewChild,
  ElementRef,
  AfterViewChecked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { SlicePipe } from '@angular/common';
import { RunStateService, DagStep } from '../services/run-state.service';
import { LogEntry, LogEntryComponent } from './log-entry.component';
import { RunEventData } from '../services/sse.service';
const STRATEGIES = [
  { id: 'thorough', label: 'Thorough' },
  { id: 'minimal', label: 'Minimal' },
  { id: 'parallel_first', label: 'Parallel' },
];


function primType(name: string): string {
  return name.split('.')[0] ?? 'connector';
}

function fmtTs(iso: string): string {
  try {
    const d = new Date(iso);
    return (
      d.toLocaleTimeString('en-GB', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }) +
      '.' +
      String(d.getMilliseconds()).padStart(3, '0')
    );
  } catch {
    return iso;
  }
}

@Component({
  selector: 'app-execution-terminal',
  standalone: true,
  imports: [FormsModule, SlicePipe, LogEntryComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="terminal">
      <!-- ── Input area ────────────────────── -->
      <div class="input-area" [class.running]="state.isRunning()">
        @if (!state.isRunning()) {
          <div class="input-row">
            <textarea
              #questionInput
              class="question-ta"
              placeholder="Ask anything about this deal — e.g. 'How does the prospectus define arrears?'"
              [ngModel]="state.questionDraft()"
              (ngModelChange)="state.questionDraft.set($event)"
              rows="2"
            ></textarea>
          </div>
          <div class="controls-row">
            <div class="strategy-pills">
              @for (s of strategies; track s.id) {
                <button
                  class="spill"
                  [class.active]="state.strategyDraft() === s.id"
                  (click)="state.strategyDraft.set(s.id)"
                >
                  {{ s.label }}
                </button>
              }
            </div>
            <button class="run-btn" [disabled]="!canRun()" (click)="launchRun()">
              ▶ Run Analysis
            </button>
          </div>
        } @else {
          <div class="running-bar">
            <span class="running-dot"></span>
            <span class="running-label"
              >{{ state.activeQuestion() | slice: 0 : 80
              }}{{ state.activeQuestion().length > 80 ? '…' : '' }}</span
            >
            <span class="running-strategy badge-strategy">{{ state.activeStrategy() }}</span>
            <div class="running-progress">
              <span class="mono progress-text"
                >{{ state.completedSteps() }}/{{ state.totalSteps() }}</span
              >
              <div class="progress-bar">
                <div class="progress-fill" [style.width.%]="state.progress()"></div>
              </div>
            </div>
            <button class="reset-btn" (click)="reset()">✕ Reset</button>
          </div>
          @if (state.phase() === 'waiting_for_input' && state.pendingClarification(); as clar) {
            <div class="clarification-box">
              <div class="clar-header">
                <span class="clar-icon">🤔</span>
                <span class="clar-label">Clarification needed</span>
                <span class="clar-step mono">{{ clar.step_id }}</span>
                <span class="clar-conf mono">conf {{ clar.confidence.toFixed(2) }}</span>
              </div>
              @if (clar.issues.length > 0) {
                <div class="clar-issues">
                  @for (iss of clar.issues; track iss) {
                    <div class="clar-issue">⚠ {{ iss }}</div>
                  }
                </div>
              }
              <div class="clar-question">{{ clar.question }}</div>
              <div class="clar-input-row">
                <textarea
                  class="clar-ta"
                  placeholder="Type your answer…"
                  [(ngModel)]="clarificationDraft"
                  rows="2"
                ></textarea>
                <button
                  class="clar-submit-btn"
                  [disabled]="!clarificationDraft.trim()"
                  (click)="submitClarification()"
                >
                  Send ↵
                </button>
              </div>
            </div>
          }
        }
      </div>

      <!-- ── Log stream ────────────────────── -->
      <div class="log-stream" #logContainer (scroll)="onScroll()">
        @if (logEntries().length === 0 && !state.isRunning()) {
          <div class="empty-state">
            <div class="empty-icon">⬡</div>
            <div class="empty-title">Framework ready</div>
            <div class="empty-sub">
              Select an analysis template from the left panel,<br />
              or type a question above and press Run Analysis.
            </div>
            <div class="empty-primitives">
              14 primitives registered · 3 orchestration strategies · governance-first
            </div>
          </div>
        }

        @for (
          entry of logEntries();
          track entry.timestamp + entry.type + (entry.primitive ?? '');
          let i = $index
        ) {
          <app-log-entry [entry]="entry" />
        }
      </div>
    </div>
  `,
  styles: [
    `
      .terminal {
        display: flex;
        flex-direction: column;
        height: 100%;
        overflow: hidden;
        background: var(--bg-canvas);
      }

      /* Input area */
      .input-area {
        padding: var(--sp-4);
        border-bottom: 1px solid var(--border);
        background: var(--bg-surface);
        flex-shrink: 0;
      }
      .input-row {
        margin-bottom: var(--sp-3);
      }

      .question-ta {
        width: 100%;
        resize: none;
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        padding: var(--sp-3);
        font-family: var(--font-sans);
        font-size: 0.875rem;
        background: var(--bg-canvas);
        color: var(--text-primary);
        transition: border-color var(--duration-fast);
        box-sizing: border-box;
      }
      .question-ta:focus {
        outline: none;
        border-color: var(--accent);
        box-shadow: 0 0 0 3px rgba(27, 111, 107, 0.1);
        background: var(--bg-surface);
      }
      .question-ta::placeholder {
        color: var(--text-muted);
        font-style: italic;
      }

      .controls-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: var(--sp-4);
      }
      .strategy-pills {
        display: flex;
        gap: var(--sp-1);
      }
      .spill {
        padding: var(--sp-1) var(--sp-3);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        background: var(--bg-canvas);
        font-size: 0.75rem;
        cursor: pointer;
        transition: all var(--duration-fast);
      }
      .spill.active {
        background: var(--accent);
        color: #fff;
        border-color: var(--accent);
      }
      .spill:not(.active):hover {
        border-color: var(--accent);
      }

      .run-btn {
        padding: var(--sp-2) var(--sp-6);
        background: var(--accent);
        color: #fff;
        border: none;
        border-radius: var(--radius-md);
        font-size: 0.875rem;
        font-weight: 600;
        cursor: pointer;
        transition: all var(--duration-fast);
      }
      .run-btn:hover:not([disabled]) {
        background: var(--accent-light);
      }
      .run-btn[disabled] {
        opacity: 0.4;
        cursor: not-allowed;
      }

      /* Running bar */
      .running-bar {
        display: flex;
        align-items: center;
        gap: var(--sp-3);
        flex-wrap: wrap;
      }
      .running-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: var(--color-prim);
        animation: pulseDot 1s ease-in-out infinite;
        flex-shrink: 0;
      }
      @keyframes pulseDot {
        0%,
        100% {
          opacity: 1;
        }
        50% {
          opacity: 0.3;
        }
      }
      .running-label {
        font-size: 0.8125rem;
        font-weight: 500;
        flex: 1;
        min-width: 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .badge-strategy {
        font-size: 0.625rem;
        font-family: var(--font-mono);
        background: rgba(27, 111, 107, 0.1);
        color: var(--accent);
        border-radius: var(--radius-sm);
        padding: 2px var(--sp-2);
      }
      .running-progress {
        display: flex;
        align-items: center;
        gap: var(--sp-2);
        flex-shrink: 0;
      }
      .progress-text {
        font-size: 0.625rem;
        color: var(--text-muted);
      }
      .progress-bar {
        width: 80px;
        height: 3px;
        background: var(--border);
        border-radius: 2px;
        overflow: hidden;
      }
      .progress-fill {
        height: 100%;
        background: var(--accent);
        transition: width var(--duration-md);
      }
      .reset-btn {
        padding: var(--sp-1) var(--sp-3);
        background: none;
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        font-size: 0.75rem;
        cursor: pointer;
        color: var(--text-muted);
        flex-shrink: 0;
      }
      .reset-btn:hover {
        border-color: var(--color-danger);
        color: var(--color-danger);
      }

      /* Clarification chat box */
      .clarification-box {
        margin-top: var(--sp-3);
        border: 1px solid var(--color-warn, #e6a817);
        border-radius: var(--radius-md);
        background: rgba(230, 168, 23, 0.06);
        padding: var(--sp-3);
      }
      .clar-header {
        display: flex;
        align-items: center;
        gap: var(--sp-2);
        margin-bottom: var(--sp-2);
      }
      .clar-icon {
        font-size: 1rem;
      }
      .clar-label {
        font-size: 0.8125rem;
        font-weight: 600;
        color: var(--text-primary);
        flex: 1;
      }
      .clar-step,
      .clar-conf {
        font-size: 0.625rem;
        color: var(--text-muted);
        background: var(--bg-canvas);
        border-radius: var(--radius-sm);
        padding: 1px var(--sp-2);
      }
      .clar-issues {
        margin-bottom: var(--sp-2);
      }
      .clar-issue {
        font-size: 0.6875rem;
        color: var(--color-warn, #e6a817);
        line-height: 1.5;
      }
      .clar-question {
        font-size: 0.875rem;
        color: var(--text-primary);
        line-height: 1.55;
        margin-bottom: var(--sp-3);
        font-style: italic;
      }
      .clar-input-row {
        display: flex;
        gap: var(--sp-2);
        align-items: flex-end;
      }
      .clar-ta {
        flex: 1;
        resize: none;
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        padding: var(--sp-2) var(--sp-3);
        font-family: var(--font-sans);
        font-size: 0.8125rem;
        background: var(--bg-canvas);
        color: var(--text-primary);
        transition: border-color var(--duration-fast);
      }
      .clar-ta:focus {
        outline: none;
        border-color: var(--color-warn, #e6a817);
      }
      .clar-submit-btn {
        padding: var(--sp-2) var(--sp-4);
        background: var(--color-warn, #e6a817);
        color: #fff;
        border: none;
        border-radius: var(--radius-md);
        font-size: 0.8125rem;
        font-weight: 600;
        cursor: pointer;
        white-space: nowrap;
        transition: opacity var(--duration-fast);
      }
      .clar-submit-btn:hover:not([disabled]) {
        opacity: 0.85;
      }
      .clar-submit-btn[disabled] {
        opacity: 0.4;
        cursor: not-allowed;
      }

      /* Log stream */
      .log-stream {
        flex: 1;
        overflow-y: auto;
        padding: 0;
        scroll-behavior: smooth;
      }

      /* Empty state */
      .empty-state {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100%;
        min-height: 300px;
        text-align: center;
        padding: var(--sp-12);
      }
      .empty-icon {
        font-size: 2.5rem;
        margin-bottom: var(--sp-4);
        opacity: 0.3;
      }
      .empty-title {
        font-size: 1.125rem;
        font-weight: 600;
        color: var(--text-primary);
        margin-bottom: var(--sp-2);
      }
      .empty-sub {
        font-size: 0.875rem;
        color: var(--text-secondary);
        line-height: 1.7;
        margin-bottom: var(--sp-4);
      }
      .empty-primitives {
        font-size: 0.6875rem;
        color: var(--text-muted);
        font-family: var(--font-mono);
      }
    `,
  ],
})
export class ExecutionTerminalComponent implements AfterViewChecked {
  @ViewChild('logContainer') private logContainer!: ElementRef<HTMLDivElement>;
  protected state = inject(RunStateService);
  protected strategies = STRATEGIES;
  protected clarificationDraft = '';

  private autoScroll = true;
  private lastEntryCount = 0;

  readonly canRun = computed(() => state_inst_questionDraft(this.state).trim().length > 0);

  readonly logEntries = computed<LogEntry[]>(() => {
    const events = this.state.events();
    const totalSteps = this.state.totalSteps();
    const entries: LogEntry[] = [];
    let stepIndex = 0;

    for (const ev of events) {
      const ts = fmtTs(ev.timestamp);
      const p = ev.payload;

      switch (ev.type) {
        case 'run_started':
          entries.push({
            type: 'orchestrator',
            timestamp: ts,
            content: `Orchestrating: "${this.state.activeQuestion()}"`,
            explanation: `Strategy: ${this.state.activeStrategy()} · 14 primitives available`,
          });
          break;

        case 'plan_ready':
          entries.push({
            type: 'plan',
            timestamp: ts,
            plan: p['steps'] as DagStep[],
            content: `${p['step_count']}-step plan · ${p['source']}`,
            explanation: p['explanation'] as string,
          });
          break;

        case 'step_started':
          stepIndex++;
          entries.push({
            type: 'step_start',
            timestamp: ts,
            stepIndex,
            totalSteps,
            primitive: p['primitive'] as string,
            primitiveType: primType(p['primitive'] as string),
          });
          break;

        case 'step_finished': {
          const cites = (p['citations'] as any[]) ?? [];
          const issues = (p['issues'] as string[]) ?? [];
          entries.push({
            type: 'step_done',
            timestamp: ts,
            primitive: p['primitive'] as string,
            primitiveType: primType(p['primitive'] as string),
            confidence: p['confidence'] as number,
            durationMs: p['duration_ms'] as number,
            citations: cites,
            issues: issues.length > 0 ? issues : undefined,
          });
          break;
        }

        case 'human_review_req':
          entries.push({
            type: 'review',
            timestamp: ts,
            primitive: p['primitive'] as string,
            primitiveType: primType(p['primitive'] as string),
            confidence: p['confidence'] as number,
            content: `Confidence ${(p['confidence'] as number).toFixed(2)} below floor ${p['floor']} → routed to human review`,
          });
          break;

        case 'human_clarification_needed':
          entries.push({
            type: 'review',
            timestamp: ts,
            primitive: p['primitive'] as string,
            primitiveType: primType(p['primitive'] as string),
            confidence: p['confidence'] as number,
            content: `Paused for clarification — conf ${(p['confidence'] as number).toFixed(2)} < ${p['floor']}`,
          });
          break;

        case 'verification_done':
          entries.push({
            type: 'verify',
            timestamp: ts,
            content: 'All citations checked against source documents',
          });
          break;

        case 'run_finished':
          entries.push({
            type: 'complete',
            timestamp: ts,
            content: `${p['step_count']} steps · ${this.state.elapsedMs() > 0 ? (this.state.elapsedMs() / 1000).toFixed(1) + 's' : ''} · ${p['review_queue_size'] ?? 0} items for human review · synthesising answer…`,
          });
          break;

        case 'run_error':
          entries.push({
            type: 'error',
            timestamp: ts,
            content: p['message'] as string,
          });
          break;
      }
    }
    return entries;
  });

  ngAfterViewChecked(): void {
    const count = this.logEntries().length;
    if (this.autoScroll && count !== this.lastEntryCount) {
      this.lastEntryCount = count;
      const el = this.logContainer?.nativeElement;
      if (el) el.scrollTop = el.scrollHeight;
    }
  }

  onScroll(): void {
    const el = this.logContainer?.nativeElement;
    if (!el) return;
    const atBottom = el.scrollHeight - el.clientHeight - el.scrollTop < 60;
    this.autoScroll = atBottom;
  }

  submitClarification(): void {
    const answer = this.clarificationDraft.trim();
    if (!answer) return;
    this.clarificationDraft = '';
    this.state.submitClarification(answer);
  }

  launchRun(): void {
    const q = this.state.questionDraft().trim();
    if (!q) return;
    this.autoScroll = true;
    this.lastEntryCount = 0;
    this.state.startQuestion(q, this.state.strategyDraft());
  }

  reset(): void {
    this.state.reset();
    this.autoScroll = true;
    this.lastEntryCount = 0;
  }
}

// Helper: read questionDraft without circular reference in computed
function state_inst_questionDraft(state: RunStateService): string {
  return state.questionDraft();
}
