import { Component, inject, ChangeDetectionStrategy } from '@angular/core';
import { RunStateService } from '../services/run-state.service';

@Component({
  selector: 'app-answer-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (state.phase() === 'done' && state.result(); as result) {
      <section class="answer-panel">
        <h2 class="answer-title">Analysis Results</h2>

        @if (state.activeQuestion()) {
          <div class="question-context">
            <span class="context-icon">❓</span>
            <span>{{ state.activeQuestion() }}</span>
            @if (state.activeStrategy() && state.activeStrategy() !== 'thorough') {
              <span class="strategy-badge badge badge-prim">{{ state.activeStrategy() }}</span>
            }
          </div>
        }

        @if (result['answer']) {
          <div class="verdict-card card">
            <div class="verdict-header">
              <span class="verdict-icon">🎯</span>
              <span class="verdict-label">Answer</span>
            </div>
            <div class="verdict-body">
              <pre class="verdict-content">{{ formatResult(result['answer']) }}</pre>
            </div>
          </div>
        }

        @if (result['comparisons'] && asArray(result['comparisons']).length > 0) {
          <div class="comparisons-card card">
            <div class="verdict-header">
              <span class="verdict-icon">📊</span>
              <span class="verdict-label">Definition Comparisons</span>
            </div>
            <div class="verdict-body">
              @for (cmp of asArray(result['comparisons']); track cmp['term']) {
                <div class="comparison-row" [class.material]="cmp['materiality'] === 'material'">
                  <div class="cmp-term">{{ cmp['term'] }}</div>
                  <div
                    class="cmp-materiality badge"
                    [class.badge-accent]="cmp['materiality'] === 'material'"
                    [class.badge-prim]="cmp['materiality'] !== 'material'"
                  >
                    {{ cmp['materiality'] }}
                  </div>
                  <div class="cmp-rationale">{{ cmp['rationale'] }}</div>
                </div>
              }
            </div>
          </div>
        }

        @if (result['assessments'] && asArray(result['assessments']).length > 0) {
          <div class="assessments-card card">
            <div class="verdict-header">
              <span class="verdict-icon">🌱</span>
              <span class="verdict-label">Impact Assessments</span>
            </div>
            <div class="verdict-body">
              @for (a of asArray(result['assessments']); track a['claim']) {
                <div class="assessment-row" [class.supported]="a['verdict'] === 'supported'">
                  <div
                    class="asm-verdict badge"
                    [class.badge-accent]="a['verdict'] === 'supported'"
                    [class.badge-prim]="a['verdict'] !== 'supported'"
                  >
                    {{ a['verdict'] }}
                  </div>
                  <div class="asm-claim">{{ a['claim'] }}</div>
                </div>
              }
            </div>
          </div>
        }

        @if (result['verification']) {
          <div class="verification-card card">
            <div class="verdict-header">
              <span class="verdict-icon" [class.ok]="verificationOk(result['verification'])">
                {{ verificationOk(result['verification']) ? '✓' : '⚠' }}
              </span>
              <span class="verdict-label">Citation Verification</span>
              <span
                class="mono verify-status"
                [class.ok-text]="verificationOk(result['verification'])"
                >{{
                  verificationOk(result['verification'])
                    ? 'All citations verified'
                    : 'Verification issues'
                }}</span
              >
            </div>
          </div>
        }

        @if (result['citations'] && asArray(result['citations']).length > 0) {
          <div class="citations-card card">
            <div class="verdict-header">
              <span class="verdict-icon">📄</span>
              <span class="verdict-label"
                >Citations ({{ asArray(result['citations']).length }})</span
              >
            </div>
            <div class="verdict-body">
              @for (c of asArray(result['citations']); track c['location']) {
                <div class="citation-row">
                  <span class="cite-source mono">{{ c['source'] }}</span>
                  <span class="cite-loc mono">{{ c['location'] }}</span>
                  <span class="cite-excerpt">{{ c['excerpt'] }}</span>
                </div>
              }
            </div>
          </div>
        }
      </section>
    }
  `,
  styles: [
    `
      .answer-panel {
        padding: var(--sp-6) var(--sp-8);
        animation: fadeInUp var(--duration-slow) var(--ease-out);
      }
      .answer-title {
        font-family: var(--font-display);
        font-weight: 400;
        font-style: italic;
        font-size: 1.5rem;
        margin-bottom: var(--sp-4);
        color: var(--text-primary);
      }
      .question-context {
        display: flex;
        align-items: flex-start;
        gap: var(--sp-2);
        padding: var(--sp-3) var(--sp-4);
        background: rgba(27, 111, 107, 0.04);
        border-radius: var(--radius-sm);
        border-left: 3px solid var(--accent);
        font-size: 0.875rem;
        color: var(--text-secondary);
        margin-bottom: var(--sp-4);
      }
      .context-icon {
        flex-shrink: 0;
      }
      .strategy-badge {
        margin-left: var(--sp-2);
        font-size: 0.6875rem;
      }

      .verdict-card,
      .verification-card,
      .comparisons-card,
      .assessments-card,
      .citations-card {
        margin-bottom: var(--sp-4);
        animation: fadeInUp var(--duration-md) var(--ease-out);
      }
      .verdict-header {
        display: flex;
        align-items: center;
        gap: var(--sp-2);
        padding: var(--sp-3) var(--sp-4);
        border-bottom: 1px solid var(--border);
        font-weight: 600;
        font-size: 0.875rem;
      }
      .verdict-icon {
        font-size: 1rem;
      }
      .verdict-icon.ok {
        color: var(--color-success);
      }
      .verdict-body {
        padding: var(--sp-4);
      }
      .verdict-content {
        white-space: pre-wrap;
        word-break: break-word;
        font-family: var(--font-sans);
        font-size: 0.8125rem;
        line-height: 1.7;
        margin: 0;
        color: var(--text-primary);
      }

      .verify-status {
        font-size: 0.75rem;
        margin-left: auto;
      }
      .ok-text {
        color: var(--color-success);
      }

      .comparison-row {
        display: grid;
        grid-template-columns: 80px 80px 1fr;
        gap: var(--sp-3);
        padding: var(--sp-2) 0;
        border-bottom: 1px solid var(--border);
        font-size: 0.8125rem;
        align-items: start;
      }
      .comparison-row:last-child {
        border-bottom: none;
      }
      .comparison-row.material {
        background: rgba(198, 40, 40, 0.03);
      }
      .cmp-term {
        font-weight: 600;
        color: var(--accent);
      }
      .cmp-rationale {
        color: var(--text-secondary);
        line-height: 1.5;
      }

      .assessment-row {
        display: flex;
        gap: var(--sp-3);
        padding: var(--sp-2) 0;
        border-bottom: 1px solid var(--border);
        font-size: 0.8125rem;
        align-items: flex-start;
      }
      .assessment-row:last-child {
        border-bottom: none;
      }
      .asm-verdict {
        flex-shrink: 0;
      }
      .asm-claim {
        color: var(--text-secondary);
        line-height: 1.5;
      }

      .citation-row {
        display: grid;
        grid-template-columns: 150px 80px 1fr;
        gap: var(--sp-3);
        padding: var(--sp-1) 0;
        font-size: 0.6875rem;
        border-bottom: 1px solid var(--border);
      }
      .citation-row:last-child {
        border-bottom: none;
      }
      .cite-source {
        color: var(--accent);
      }
      .cite-loc {
        color: var(--text-muted);
      }
      .cite-excerpt {
        color: var(--text-secondary);
      }
    `,
  ],
})
export class AnswerPanelComponent {
  protected state = inject(RunStateService);

  formatResult(val: unknown): string {
    if (typeof val === 'string') return val;
    if (val === null || val === undefined) return '';
    return JSON.stringify(val, null, 2);
  }

  asArray(val: unknown): any[] {
    return Array.isArray(val) ? val : [];
  }

  verificationOk(val: unknown): boolean {
    if (typeof val === 'object' && val !== null) {
      return (val as any)['ok'] === true;
    }
    return false;
  }
}
