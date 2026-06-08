import {
  Component,
  input,
  computed,
  ChangeDetectionStrategy,
  signal,
} from '@angular/core';
import { StepEvent } from '../services/run-state.service';

interface AgentPanel {
  stepId: string;
  primitive: string;
  label: string;
  line: number;
  lineLabel: string;
  status: 'waiting' | 'running' | 'done' | 'error';
  payload?: Record<string, unknown>;
}

@Component({
  selector: 'app-lod-results',
  standalone: true,
  imports: [],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="lod-panels">
      @for (panel of panels(); track panel.stepId) {
        <div class="agent-card" [class]="'status-' + panel.status">
          <!-- Header -->
          <div class="agent-header">
            <div class="agent-meta">
              <span class="line-badge">{{ panel.lineLabel }}</span>
              <span class="agent-name">{{ panel.label }}</span>
            </div>
            <div class="agent-status">
              @if (panel.status === 'waiting') {
                <span class="status-chip waiting">Awaiting</span>
              } @else if (panel.status === 'running') {
                <span class="status-chip running">
                  <span class="running-dot"></span>Analyzing…
                </span>
              } @else if (panel.status === 'done') {
                @if (panel.primitive === 'lod.credit') {
                  <span class="verdict-badge" [class]="ragClass(panel.payload?.['rag'])">
                    {{ panel.payload?.['rag'] ?? 'N/A' }}
                  </span>
                } @else if (panel.primitive === 'lod.risk') {
                  <span class="verdict-badge" [class]="scoreClass(panel.payload?.['score'])">
                    Risk {{ panel.payload?.['score'] ?? '—' }}/10
                  </span>
                } @else if (panel.primitive === 'lod.audit') {
                  <span class="verdict-badge" [class]="verdictClass(panel.payload?.['verdict'])">
                    {{ panel.payload?.['verdict'] ?? 'N/A' }}
                  </span>
                }
              }
            </div>
          </div>

          <!-- Body -->
          @if (panel.status === 'waiting') {
            <div class="agent-body muted">
              <span>Awaiting prior agent to complete…</span>
            </div>
          } @else if (panel.status === 'running') {
            <div class="agent-body muted">
              <span>Analyzing deal data…</span>
            </div>
          } @else if (panel.status === 'done' && panel.payload) {

            <!-- Credit Agent -->
            @if (panel.primitive === 'lod.credit') {
              @if (panel.payload['justification']) {
                <div class="justification">{{ panel.payload['justification'] }}</div>
              }
              @if (panel.payload['analysis']) {
                <div class="analysis" [class.collapsed]="!expanded(panel.stepId)" (click)="toggle(panel.stepId)">
                  <div class="analysis-text">{{ panel.payload['analysis'] }}</div>
                  <button class="expand-link">{{ expanded(panel.stepId) ? 'Show less ↑' : 'Show more ↓' }}</button>
                </div>
              }
              @if (asArray(panel.payload['data_gaps'])?.length) {
                <div class="gaps-list">
                  <span class="gaps-label">Data gaps:</span>
                  @for (gap of asArray(panel.payload['data_gaps']); track gap) {
                    <span class="gap-item">{{ gap }}</span>
                  }
                </div>
              }
            }

            <!-- Risk Agent -->
            @if (panel.primitive === 'lod.risk') {
              @if (asArray(panel.payload['flags'])?.length) {
                <ul class="flags-list">
                  @for (flag of asArray(panel.payload['flags']); track flag) {
                    <li class="flag-item">{{ flag }}</li>
                  }
                </ul>
              }
              @if (panel.payload['analysis']) {
                <div class="analysis" [class.collapsed]="!expanded(panel.stepId)" (click)="toggle(panel.stepId)">
                  <div class="analysis-text">{{ panel.payload['analysis'] }}</div>
                  <button class="expand-link">{{ expanded(panel.stepId) ? 'Show less ↑' : 'Show more ↓' }}</button>
                </div>
              }
              @if (panel.payload['credit_assessment_challenge']) {
                <div class="challenge-note">
                  <span class="challenge-label">Challenge:</span>
                  {{ panel.payload['credit_assessment_challenge'] }}
                </div>
              }
            }

            <!-- Audit Agent -->
            @if (panel.primitive === 'lod.audit') {
              @if (asArray(panel.payload['findings'])?.length) {
                <ul class="findings-list">
                  @for (finding of asArray(panel.payload['findings']); track finding) {
                    <li class="finding-item">{{ finding }}</li>
                  }
                </ul>
              }
              @if (panel.payload['analysis']) {
                <div class="analysis" [class.collapsed]="!expanded(panel.stepId)" (click)="toggle(panel.stepId)">
                  <div class="analysis-text">{{ panel.payload['analysis'] }}</div>
                  <button class="expand-link">{{ expanded(panel.stepId) ? 'Show less ↑' : 'Show more ↓' }}</button>
                </div>
              }
              @if (panel.payload['prior_agent_challenges']) {
                <div class="challenge-note">
                  <span class="challenge-label">Assessment review:</span>
                  {{ panel.payload['prior_agent_challenges'] }}
                </div>
              }
            }
          }
        </div>
      }
    </div>
  `,
  styles: [`
    .lod-panels {
      display: flex;
      flex-direction: column;
      gap: var(--sp-4);
      padding: var(--sp-4);
    }

    .agent-card {
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      background: var(--bg-surface);
      overflow: hidden;
      transition: box-shadow var(--duration-md);
    }
    .agent-card.status-running {
      border-color: var(--color-prim);
      animation: borderPulse 2s ease-in-out infinite;
    }
    .agent-card.status-waiting {
      opacity: 0.55;
    }

    .agent-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--sp-3) var(--sp-4);
      border-bottom: 1px solid var(--border);
      background: var(--bg-canvas);
    }
    .agent-meta {
      display: flex;
      align-items: center;
      gap: var(--sp-3);
    }
    .line-badge {
      font-size: 0.625rem;
      font-family: var(--font-mono);
      font-weight: 700;
      background: rgba(27, 111, 107, 0.1);
      color: var(--accent);
      border-radius: var(--radius-sm);
      padding: 2px var(--sp-2);
      letter-spacing: 0.05em;
      white-space: nowrap;
    }
    .agent-name {
      font-size: 0.9375rem;
      font-weight: 600;
      color: var(--text-primary);
    }

    /* Status chips */
    .status-chip {
      font-size: 0.6875rem;
      font-family: var(--font-mono);
      border-radius: var(--radius-sm);
      padding: 2px var(--sp-2);
      display: flex;
      align-items: center;
      gap: var(--sp-1);
    }
    .status-chip.waiting {
      background: var(--bg-canvas);
      color: var(--text-muted);
    }
    .status-chip.running {
      background: rgba(45, 90, 142, 0.1);
      color: var(--color-prim);
    }
    .running-dot {
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--color-prim);
      animation: pulseDot 1s ease-in-out infinite;
      flex-shrink: 0;
    }
    @keyframes pulseDot {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.3; }
    }

    /* Verdict badges */
    .verdict-badge {
      font-size: 0.6875rem;
      font-weight: 700;
      font-family: var(--font-mono);
      border-radius: var(--radius-sm);
      padding: 3px var(--sp-3);
      letter-spacing: 0.04em;
    }
    .rag-green  { background: rgba(46, 125, 50, 0.12); color: var(--color-success); border: 1px solid rgba(46, 125, 50, 0.3); }
    .rag-amber  { background: rgba(230, 81, 0, 0.1); color: var(--color-warning); border: 1px solid rgba(230, 81, 0, 0.3); }
    .rag-red    { background: rgba(198, 40, 40, 0.1); color: var(--color-danger); border: 1px solid rgba(198, 40, 40, 0.3); }
    .score-low  { background: rgba(46, 125, 50, 0.12); color: var(--color-success); border: 1px solid rgba(46, 125, 50, 0.3); }
    .score-mid  { background: rgba(230, 81, 0, 0.1); color: var(--color-warning); border: 1px solid rgba(230, 81, 0, 0.3); }
    .score-high { background: rgba(198, 40, 40, 0.1); color: var(--color-danger); border: 1px solid rgba(198, 40, 40, 0.3); }
    .verdict-pass      { background: rgba(46, 125, 50, 0.12); color: var(--color-success); border: 1px solid rgba(46, 125, 50, 0.3); }
    .verdict-cond-pass { background: rgba(230, 81, 0, 0.1); color: var(--color-warning); border: 1px solid rgba(230, 81, 0, 0.3); }
    .verdict-fail      { background: rgba(198, 40, 40, 0.1); color: var(--color-danger); border: 1px solid rgba(198, 40, 40, 0.3); }

    /* Body */
    .agent-body {
      padding: var(--sp-4);
    }
    .agent-body.muted {
      color: var(--text-muted);
      font-size: 0.8125rem;
      font-style: italic;
    }

    .justification {
      font-size: 0.9rem;
      font-weight: 500;
      color: var(--text-primary);
      padding: var(--sp-3) var(--sp-4);
      border-left: 3px solid var(--accent);
      margin: var(--sp-3) var(--sp-4) 0;
    }

    .analysis {
      padding: var(--sp-3) var(--sp-4);
      cursor: pointer;
    }
    .analysis.collapsed .analysis-text {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 3;
      overflow: hidden;
    }
    .analysis-text {
      font-size: 0.8125rem;
      color: var(--text-secondary);
      line-height: 1.65;
      white-space: pre-line;
    }
    .expand-link {
      background: none;
      border: none;
      font-size: 0.6875rem;
      color: var(--accent);
      cursor: pointer;
      padding: var(--sp-1) 0;
      margin-top: var(--sp-1);
    }

    .flags-list,
    .findings-list {
      list-style: none;
      padding: var(--sp-3) var(--sp-4) 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: var(--sp-2);
    }
    .flag-item,
    .finding-item {
      font-size: 0.8125rem;
      color: var(--text-primary);
      display: flex;
      align-items: flex-start;
      gap: var(--sp-2);
    }
    .flag-item::before {
      content: '⚑';
      color: var(--color-warning);
      flex-shrink: 0;
      font-size: 0.75rem;
      margin-top: 1px;
    }
    .finding-item::before {
      content: '▸';
      color: var(--accent);
      flex-shrink: 0;
      font-size: 0.75rem;
      margin-top: 2px;
    }

    .gaps-list {
      padding: var(--sp-2) var(--sp-4) var(--sp-3);
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--sp-2);
    }
    .gaps-label {
      font-size: 0.6875rem;
      color: var(--text-muted);
      font-weight: 600;
    }
    .gap-item {
      font-size: 0.6875rem;
      background: var(--bg-canvas);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 1px var(--sp-2);
      color: var(--text-secondary);
    }

    .challenge-note {
      margin: 0 var(--sp-4) var(--sp-3);
      padding: var(--sp-2) var(--sp-3);
      background: rgba(123, 94, 167, 0.06);
      border-radius: var(--radius-sm);
      font-size: 0.7813rem;
      color: var(--text-secondary);
      line-height: 1.5;
    }
    .challenge-label {
      font-weight: 600;
      color: var(--color-agent);
      margin-right: var(--sp-1);
    }
  `],
})
export class LodResultsComponent {
  readonly steps = input.required<StepEvent[]>();
  // Real-time agent outputs keyed by step_id — populated as LOD_AGENT_FINISHED events fire
  readonly lodOutputs = input<Record<string, Record<string, unknown>>>({});

  private expandedSteps = signal<Set<string>>(new Set());

  readonly panels = computed<AgentPanel[]>(() => {
    const steps = this.steps();
    const outputs = this.lodOutputs();

    // Metadata keyed by primitive name — stable regardless of what step_id the
    // LLM planner chose.
    const PRIMITIVE_META: Record<string, { label: string; line: number; lineLabel: string }> = {
      'lod.credit': { label: 'Credit Agent', line: 1, lineLabel: '1st Line of Defense' },
      'lod.risk':   { label: 'Risk Agent',   line: 2, lineLabel: '2nd Line of Defense' },
      'lod.audit':  { label: 'Audit Agent',  line: 3, lineLabel: '3rd Line of Defense' },
    };

    // Find all LoD steps that have actually appeared in the run (from step_started events).
    const lodSteps = steps.filter(s => s.primitive?.startsWith('lod.'));

    // Build one panel per known lod primitive, in line order.
    const primitiveOrder = ['lod.credit', 'lod.risk', 'lod.audit'];
    return primitiveOrder.map(primitive => {
      const meta = PRIMITIVE_META[primitive];
      // Find the actual step for this primitive (dynamic step_id from the plan)
      const step = lodSteps.find(s => s.primitive === primitive);
      // Derive the step_id — fall back to the recipe default so outputs remain
      // accessible when running the hardcoded 3LoD fallback plan.
      const stepId = step?.step_id ?? primitive.replace('.', '_');
      const payload = outputs[stepId];
      return {
        stepId,
        primitive,
        label: meta.label,
        line: meta.line,
        lineLabel: meta.lineLabel,
        status: step ? step.status : 'waiting' as const,
        payload,
      };
    });
  });

  expanded(stepId: string): boolean {
    return this.expandedSteps().has(stepId);
  }

  toggle(stepId: string): void {
    this.expandedSteps.update((s) => {
      const next = new Set(s);
      if (next.has(stepId)) {
        next.delete(stepId);
      } else {
        next.add(stepId);
      }
      return next;
    });
  }

  asArray(val: unknown): string[] | null {
    if (!Array.isArray(val) || val.length === 0) return null;
    return val as string[];
  }

  ragClass(rag: unknown): string {
    const r = String(rag ?? '').toUpperCase();
    if (r === 'GREEN') return 'verdict-badge rag-green';
    if (r === 'RED') return 'verdict-badge rag-red';
    return 'verdict-badge rag-amber';
  }

  scoreClass(score: unknown): string {
    const n = Number(score ?? 5);
    if (n <= 3) return 'verdict-badge score-low';
    if (n <= 6) return 'verdict-badge score-mid';
    return 'verdict-badge score-high';
  }

  verdictClass(verdict: unknown): string {
    const v = String(verdict ?? '').toUpperCase();
    if (v === 'PASS') return 'verdict-badge verdict-pass';
    if (v === 'FAIL') return 'verdict-badge verdict-fail';
    return 'verdict-badge verdict-cond-pass';
  }
}
