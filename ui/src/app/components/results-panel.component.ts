import { Component, inject, signal, computed, ChangeDetectionStrategy, effect } from '@angular/core';
import { RunStateService } from '../services/run-state.service';
import { ApiService } from '../services/api.service';

type Tab = 'answer' | 'citations' | 'audit' | 'trace';

interface CitationGroup { source: string; items: { location: string; excerpt: string }[]; }

@Component({
  selector: 'app-results-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="results-panel">

      <!-- Tab bar -->
      <div class="tab-bar">
        @for (tab of tabs; track tab.id) {
          <button
            class="tab-btn"
            [class.active]="activeTab() === tab.id"
            (click)="selectTab(tab.id)"
          >
            {{ tab.label }}
            @if (tab.id === 'citations' && allCitations().length > 0) {
              <span class="tab-count">{{ allCitations().length }}</span>
            }
            @if (tab.id === 'audit' && state.events().length > 0) {
              <span class="tab-count">{{ state.events().length }}</span>
            }
          </button>
        }
      </div>

      <div class="panel-body">

        <!-- ── ANSWER TAB ──────────────────────── -->
        @if (activeTab() === 'answer') {
          <div class="tab-content">
            @if (state.phase() === 'idle') {
              <div class="panel-empty">
                <span class="panel-empty-icon">◎</span>
                <p>Results will appear here when the analysis completes.</p>
              </div>
            } @else if (state.phase() === 'planning' || state.phase() === 'executing') {
              <div class="panel-loading">
                <div class="loading-steps">
                  @for (i of [1,2,3,4,5,6]; track i) {
                    <div class="loading-row" [style.animation-delay.ms]="i * 120">
                      <div class="loading-bar"></div>
                    </div>
                  }
                </div>
                <p class="loading-label">Orchestrating analysis…</p>
              </div>
            } @else if (state.phase() === 'error') {
              <div class="error-card">
                <span class="err-icon">✕</span>
                <span>{{ state.error() ?? 'Run failed' }}</span>
              </div>
            } @else if (state.result(); as result) {
              <!-- Question context -->
              <div class="question-ctx">
                <span class="q-icon">❓</span>
                <span class="q-text">{{ state.activeQuestion() }}</span>
                <span class="strategy-chip mono">{{ state.activeStrategy() }}</span>
              </div>

              <!-- Verification badge -->
              @if (result['verification']) {
                <div class="verify-badge" [class.ok]="verOk(result['verification'])">
                  <span>{{ verOk(result['verification']) ? '✓ All citations verified' : '⚠ Verification issues' }}</span>
                  <span class="mono verify-ct">{{ verTotal(result['verification']) }} checked</span>
                </div>
              }

              <!-- Human review queue — prominent alert with details -->
              @if (asArr(result['review_queue']).length > 0) {
                <div class="review-section">
                  <div class="review-header">
                    <span class="review-header-icon">⚠</span>
                    <span class="review-header-label">Human Review Required</span>
                    <span class="review-count mono">{{ asArr(result['review_queue']).length }}</span>
                  </div>
                  @for (item of asArr(result['review_queue']); track item['step_id']) {
                    <div class="review-item">
                      <div class="review-item-top">
                        <span class="ptype-mini" [class]="'ptype-' + primTypeOf(item['primitive'])">{{ primTypeLabel(item['primitive']) }}</span>
                        <span class="review-item-prim mono">{{ item['primitive'] }}</span>
                        <span class="review-item-conf conf-low mono">conf {{ (item['confidence'] ?? 0).toFixed(2) }} &lt; {{ item['floor'] }}</span>
                      </div>
                      @if (asArr(item['issues']).length > 0) {
                        <div class="review-item-issues">
                          @for (iss of asArr(item['issues']); track iss) {
                            <div class="review-issue-row">{{ iss }}</div>
                          }
                        </div>
                      }
                      <div class="review-item-action">
                        Output included in results — manual verification recommended before use in production.
                      </div>
                    </div>
                  }
                </div>
              }

              <!-- Analyst clarifications exchanged during the run -->
              @if (asArr(result['clarifications']).length > 0) {
                <div class="clarifications-section">
                  <div class="sec-label">ANALYST CLARIFICATIONS</div>
                  @for (c of asArr(result['clarifications']); track c['step_id']) {
                    <div class="clar-item">
                      <div class="clar-item-q">🤔 {{ c['question'] }}</div>
                      <div class="clar-item-a">↳ {{ c['answer'] }}</div>
                    </div>
                  }
                </div>
              }

              <!-- Waterfall steps (extractor.waterfall output) -->
              @if (waterfallSteps(result['answer']).length > 0) {
                <div class="answer-section">
                  <div class="sec-label">PRIORITY OF PAYMENTS — {{ waterfallSteps(result['answer']).length }} STEPS</div>
                  @for (step of waterfallSteps(result['answer']); track step['rank']) {
                    <div class="waterfall-row">
                      <div class="wf-rank">{{ step['rank'] }}</div>
                      <div class="wf-body">
                        <div class="wf-beneficiary">{{ step['beneficiary'] }}</div>
                        <div class="wf-basis">{{ step['amount_basis'] }}</div>
                        @if (step['conditions'] && step['conditions'] !== 'none') {
                          <div class="wf-conditions">⚑ {{ step['conditions'] }}</div>
                        }
                        @if (step['excerpt']) {
                          <div class="wf-excerpt">"{{ truncate(step['excerpt'], 120) }}"</div>
                        }
                      </div>
                      <div class="wf-page mono">p.{{ step['page'] }}</div>
                    </div>
                  }
                </div>
              }

              <!-- Plain string answer -->
              @if (isStringAnswer(result['answer'])) {
                <div class="answer-section">
                  <div class="sec-label">ANSWER</div>
                  <div class="answer-body">{{ result['answer'] }}</div>
                </div>
              }

              <!-- Generic object answer (not waterfall, not string) -->
              @if (isGenericAnswer(result['answer'])) {
                <div class="answer-section">
                  <div class="sec-label">ANSWER</div>
                  <pre class="answer-json">{{ fmtAnswer(result['answer']) }}</pre>
                </div>
              }

              <!-- Term comparisons -->
              @if (asArr(result['comparisons']).length > 0) {
                <div class="comparisons-section">
                  <div class="sec-label">DEFINITION COMPARISONS</div>
                  @for (cmp of asArr(result['comparisons']); track cmp['term']) {
                    <div class="cmp-row" [class.material]="cmp['materiality'] === 'material'">
                      <div class="cmp-term">{{ cmp['term'] }}</div>
                      <div class="cmp-mat-badge" [class]="'mat-' + cmp['materiality']">{{ cmp['materiality'] }}</div>
                      <div class="cmp-rationale">{{ cmp['rationale'] }}</div>
                    </div>
                  }
                </div>
              }

              <!-- Impact assessments -->
              @if (asArr(result['assessments']).length > 0) {
                <div class="assessments-section">
                  <div class="sec-label">IMPACT ASSESSMENTS</div>
                  @for (a of asArr(result['assessments']); track a['claim']) {
                    <div class="asm-row">
                      <div class="asm-verdict" [class]="'verdict-' + a['verdict']">{{ a['verdict'] }}</div>
                      <div class="asm-claim">{{ truncate(a['claim'], 80) }}</div>
                    </div>
                  }
                </div>
              }
            }
          </div>
        }

        <!-- ── CITATIONS TAB ──────────────────── -->
        @if (activeTab() === 'citations') {
          <div class="tab-content">
            @if (allCitations().length === 0) {
              <div class="panel-empty">
                <span class="panel-empty-icon">📄</span>
                <p>Citations will appear here as steps complete.</p>
              </div>
            } @else {
              @for (group of citationGroups(); track group.source) {
                <div class="cite-group">
                  <div class="cite-group-header">
                    <span class="cite-source-name">{{ group.source }}</span>
                    <span class="cite-count mono">{{ group.items.length }}</span>
                  </div>
                  @for (item of group.items; track item.location) {
                    <div class="cite-item">
                      <span class="cite-loc-badge mono">{{ item.location }}</span>
                      <span class="cite-excerpt-text">"{{ truncate(item.excerpt, 100) }}"</span>
                    </div>
                  }
                </div>
              }
            }
          </div>
        }

        <!-- ── AUDIT TAB ─────────────────────── -->
        @if (activeTab() === 'audit') {
          <div class="tab-content">
            @if (state.events().length === 0) {
              <div class="panel-empty">
                <span class="panel-empty-icon">📋</span>
                <p>Audit trail will appear as the run executes.</p>
              </div>
            } @else {
              <!-- Confidence sparkline -->
              @if (confScores().length > 0) {
                <div class="conf-spark-section">
                  <div class="sec-label">CONFIDENCE PER STEP</div>
                  <div class="conf-spark">
                    @for (c of confScores(); track $index) {
                      <div class="spark-bar-wrap" [title]="c.primitive + ': ' + c.confidence.toFixed(2)">
                        <div class="spark-bar" [style.height.%]="c.confidence * 100" [class]="confBarClass(c.confidence)"></div>
                        <span class="spark-label mono">{{ c.confidence.toFixed(2) }}</span>
                      </div>
                    }
                  </div>
                </div>
              }

              <!-- Event list -->
              <div class="sec-label" style="margin-top: var(--sp-4)">EVENT LOG</div>
              @for (ev of state.events(); track ev.timestamp + ev.type) {
                <div class="audit-row">
                  <span class="audit-ts mono">{{ fmtTs(ev.timestamp) }}</span>
                  <span class="audit-type mono" [class]="'atype-' + ev.type">{{ ev.type }}</span>
                  <span class="audit-detail">{{ auditDetail(ev) }}</span>
                </div>
              }
            }
          </div>
        }

        <!-- ── TRACE TAB ─────────────────────── -->
        @if (activeTab() === 'trace') {
          <div class="tab-content">
            @if (state.phase() === 'idle') {
              <div class="panel-empty">
                <span class="panel-empty-icon">🔬</span>
                <p>Run an analysis to generate a trace.</p>
              </div>
            } @else if (traceLoading()) {
              <div class="panel-loading">
                <div class="loading-steps">
                  @for (i of [1,2,3]; track i) {
                    <div class="loading-row"><div class="loading-bar"></div></div>
                  }
                </div>
                <p class="loading-label">Loading trace…</p>
              </div>
            } @else if (!traceData()) {
              <div class="panel-empty">
                <span class="panel-empty-icon">⏳</span>
                <p>Trace will be available when the run completes.</p>
              </div>
            } @else {
              <div class="trace-meta">
                <div class="trace-row">
                  <span class="trace-key">Duration</span>
                  <span class="trace-val mono">{{ fmtMs(traceData()!['duration_ms']) }}</span>
                </div>
                <div class="trace-row">
                  <span class="trace-key">Strategy</span>
                  <span class="trace-val mono">{{ traceData()!['strategy'] }}</span>
                </div>
                <div class="trace-row">
                  <span class="trace-key">Steps</span>
                  <span class="trace-val mono">{{ asArr(traceData()!['steps']).length }}</span>
                </div>
              </div>
              <div class="sec-label" style="margin-top: var(--sp-4)">STEP DETAILS</div>
              @for (step of asArr(traceData()!['steps']); track step['step_id']) {
                <div class="trace-step" [class.expanded]="expandedStep() === step['step_id']">
                  <button class="trace-step-header" (click)="toggleStep(step['step_id'])">
                    <span class="ptype-mini" [class]="'ptype-' + primTypeOf(step['primitive'])">{{ primTypeLabel(step['primitive']) }}</span>
                    <span class="trace-step-name mono">{{ step['step_id'] }}</span>
                    <span class="trace-step-prim">{{ step['primitive'] }}</span>
                    <span class="conf-mini" [class]="confClass(step['output']?.['confidence'])">
                      {{ (step['output']?.['confidence'] ?? 0).toFixed(2) }}
                    </span>
                    <span class="trace-step-dur mono">{{ fmtMs(step['duration_ms']) }}</span>
                    <span class="expand-arrow">{{ expandedStep() === step['step_id'] ? '▾' : '▸' }}</span>
                  </button>
                  @if (expandedStep() === step['step_id']) {
                    <div class="trace-step-body">
                      <!-- Inputs -->
                      <div class="trace-section-label">INPUTS</div>
                      <pre class="trace-json">{{ fmtJson(step['input_args']) }}</pre>
                      <!-- Output payload -->
                      <div class="trace-section-label">OUTPUT</div>
                      <pre class="trace-json">{{ fmtJson(step['output']?.['payload']) }}</pre>
                      <!-- Citations -->
                      @if (asArr(step['output']?.['citations']).length > 0) {
                        <div class="trace-section-label">CITATIONS ({{ asArr(step['output']?.['citations']).length }})</div>
                        @for (c of asArr(step['output']?.['citations']); track c['location']) {
                          <div class="trace-cite">
                            <span class="cite-loc-badge mono">{{ c['location'] }}</span>
                            <span class="cite-excerpt-text">"{{ truncate(c['excerpt'], 80) }}"</span>
                          </div>
                        }
                      }
                      <!-- Issues -->
                      @if (asArr(step['output']?.['issues']).length > 0) {
                        <div class="trace-section-label">ISSUES</div>
                        @for (issue of asArr(step['output']?.['issues']); track issue) {
                          <div class="trace-issue">⚠ {{ issue }}</div>
                        }
                      }
                      <!-- LLM calls -->
                      @if (asArr(step['llm_calls']).length > 0) {
                        <div class="trace-section-label">LLM CALLS ({{ asArr(step['llm_calls']).length }})</div>
                        @for (call of asArr(step['llm_calls']); track call['seq']) {
                          <div class="llm-call">
                            <div class="llm-call-meta">
                              <span class="mono">prompt {{ call['prompt_chars'] }} chars</span>
                              <span class="mono">response {{ call['response_chars'] }} chars</span>
                              <span [class.ok-text]="call['parsed_ok']" [class.err-text]="!call['parsed_ok']">
                                {{ call['parsed_ok'] ? '✓ parsed' : '✕ failed' }}
                              </span>
                            </div>
                            <div class="llm-prompt-preview">{{ call['prompt_preview'] }}</div>
                            <div class="llm-resp-preview">→ {{ call['response_preview'] }}</div>
                          </div>
                        }
                      }
                    </div>
                  }
                </div>
              }
            }
          </div>
        }

      </div>
    </div>
  `,
  styles: [`
    .results-panel {
      width: 380px;
      min-width: 380px;
      height: 100%;
      border-left: 1px solid var(--border);
      background: var(--bg-surface);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }

    .tab-bar {
      display: flex;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }
    .tab-btn {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: var(--sp-1);
      padding: var(--sp-3) var(--sp-2);
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      cursor: pointer;
      font-size: 0.75rem;
      font-weight: 500;
      color: var(--text-muted);
      transition: all var(--duration-fast);
    }
    .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }
    .tab-btn:hover:not(.active) { color: var(--text-secondary); }
    .tab-count {
      background: var(--bg-canvas);
      border: 1px solid var(--border);
      border-radius: var(--radius-full);
      padding: 0 var(--sp-1);
      font-size: 0.5625rem;
      font-family: var(--font-mono);
      color: var(--text-muted);
    }

    .panel-body { flex: 1; overflow-y: auto; }
    .tab-content { padding: var(--sp-4); }

    /* Empty / loading states */
    .panel-empty {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--sp-3);
      padding: var(--sp-12) var(--sp-4);
      text-align: center;
    }
    .panel-empty-icon { font-size: 2rem; opacity: 0.3; }
    .panel-empty p { font-size: 0.8125rem; color: var(--text-muted); }

    .panel-loading { padding: var(--sp-4); }
    .loading-steps { display: flex; flex-direction: column; gap: var(--sp-2); margin-bottom: var(--sp-4); }
    .loading-row { animation: loadingPulse 1.4s ease-in-out infinite; }
    .loading-bar { height: 8px; background: var(--border); border-radius: 4px; }
    @keyframes loadingPulse { 0%,100% { opacity:0.4; } 50% { opacity:1; } }
    .loading-label { font-size: 0.75rem; color: var(--text-muted); text-align: center; }

    .error-card {
      display: flex;
      gap: var(--sp-2);
      padding: var(--sp-4);
      background: rgba(198,40,40,.06);
      border: 1px solid rgba(198,40,40,.2);
      border-radius: var(--radius-md);
      color: var(--color-danger);
      font-size: 0.8125rem;
    }
    .err-icon { font-size: 1rem; }

    /* Answer content */
    .question-ctx {
      display: flex;
      align-items: flex-start;
      gap: var(--sp-2);
      padding: var(--sp-3);
      background: rgba(27,111,107,.04);
      border-radius: var(--radius-sm);
      border-left: 3px solid var(--accent);
      margin-bottom: var(--sp-4);
      font-size: 0.8125rem;
    }
    .q-icon { flex-shrink: 0; }
    .q-text { flex: 1; color: var(--text-secondary); line-height: 1.5; }
    .strategy-chip { font-size: 0.5625rem; background: rgba(27,111,107,.1); color: var(--accent); border-radius: var(--radius-sm); padding: 2px var(--sp-2); flex-shrink: 0; }

    .verify-badge {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: var(--sp-2) var(--sp-3);
      border-radius: var(--radius-sm);
      margin-bottom: var(--sp-3);
      font-size: 0.75rem;
      font-weight: 500;
      background: rgba(198,40,40,.06);
      color: var(--color-danger);
    }
    .verify-badge.ok { background: rgba(46,125,50,.06); color: var(--color-success); }
    .verify-ct { font-size: 0.5625rem; }

    /* Review queue section */
    .review-section {
      border: 1px solid rgba(230,81,0,.3);
      border-radius: var(--radius-md);
      margin-bottom: var(--sp-4);
      overflow: hidden;
    }
    .review-header {
      display: flex;
      align-items: center;
      gap: var(--sp-2);
      padding: var(--sp-2) var(--sp-3);
      background: rgba(230,81,0,.06);
      border-bottom: 1px solid rgba(230,81,0,.2);
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--color-warning);
    }
    .review-header-label { flex: 1; }
    .review-count { font-size: 0.5625rem; background: rgba(230,81,0,.15); border-radius: var(--radius-full); padding: 0 var(--sp-2); }
    .review-item { padding: var(--sp-3); border-bottom: 1px solid rgba(230,81,0,.1); }
    .review-item:last-child { border-bottom: none; }
    .review-item-top { display: flex; align-items: center; gap: var(--sp-2); margin-bottom: var(--sp-1); }
    .review-item-prim { font-size: 0.6875rem; font-weight: 500; }
    .review-item-conf { font-size: 0.625rem; }
    .review-item-issues { margin: var(--sp-1) 0; padding-left: var(--sp-3); }
    .review-issue-row { font-size: 0.625rem; color: var(--color-warning); line-height: 1.5; }
    .review-item-action {
      font-size: 0.5625rem;
      color: var(--text-muted);
      font-style: italic;
      padding: var(--sp-1) var(--sp-2);
      background: rgba(230,81,0,.04);
      border-radius: var(--radius-sm);
      margin-top: var(--sp-1);
    }

    /* Waterfall steps */
    .waterfall-row {
      display: grid;
      grid-template-columns: 24px 1fr 32px;
      gap: var(--sp-3);
      padding: var(--sp-2) 0;
      border-bottom: 1px solid var(--border);
      align-items: flex-start;
    }
    .waterfall-row:last-child { border-bottom: none; }
    .wf-rank {
      width: 24px; height: 24px; border-radius: 50%;
      background: var(--accent); color: #fff;
      display: flex; align-items: center; justify-content: center;
      font-size: 0.5625rem; font-weight: 700; flex-shrink: 0;
    }
    .wf-body { display: flex; flex-direction: column; gap: 2px; }
    .wf-beneficiary { font-size: 0.75rem; font-weight: 600; color: var(--text-primary); }
    .wf-basis { font-size: 0.625rem; color: var(--text-secondary); line-height: 1.4; }
    .wf-conditions { font-size: 0.5625rem; color: var(--color-warning); }
    .wf-excerpt { font-size: 0.5625rem; color: var(--text-muted); font-style: italic; line-height: 1.4; }
    .wf-page { font-size: 0.5rem; color: var(--text-muted); padding-top: 4px; }

    .answer-json {
      font-size: 0.5625rem; font-family: var(--font-mono); white-space: pre-wrap;
      word-break: break-all; background: var(--bg-canvas); border: 1px solid var(--border);
      border-radius: var(--radius-sm); padding: var(--sp-3); max-height: 300px;
      overflow-y: auto; color: var(--text-secondary); margin: 0;
    }

    .sec-label {
      font-size: 0.5625rem;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-bottom: var(--sp-2);
    }

    .answer-section { margin-bottom: var(--sp-4); }
    .answer-body {
      font-size: 0.8125rem;
      line-height: 1.7;
      color: var(--text-primary);
      white-space: pre-wrap;
      word-break: break-word;
    }

    /* Comparisons */
    .comparisons-section { margin-bottom: var(--sp-4); }
    .clarifications-section { margin-bottom: var(--sp-4); }
    .clar-item {
      padding: var(--sp-2) 0;
      border-bottom: 1px solid var(--border);
    }
    .clar-item:last-child { border-bottom: none; }
    .clar-item-q {
      font-size: 0.8125rem;
      color: var(--text-secondary);
      margin-bottom: var(--sp-1);
      font-style: italic;
    }
    .clar-item-a {
      font-size: 0.8125rem;
      color: var(--text-primary);
      padding-left: var(--sp-4);
    }
    .cmp-row {
      display: grid;
      grid-template-columns: 70px 70px 1fr;
      gap: var(--sp-2);
      padding: var(--sp-2) 0;
      border-bottom: 1px solid var(--border);
      font-size: 0.75rem;
      align-items: start;
    }
    .cmp-row:last-child { border-bottom: none; }
    .cmp-term { font-weight: 600; color: var(--accent); font-size: 0.6875rem; }
    .cmp-mat-badge { font-size: 0.5rem; font-family: var(--font-mono); font-weight: 700; padding: 2px 4px; border-radius: var(--radius-sm); }
    .mat-material { background: rgba(198,40,40,.15); color: var(--color-danger); }
    .mat-moderate  { background: rgba(230,81,0,.15); color: var(--color-warning); }
    .mat-none      { background: rgba(46,125,50,.1); color: var(--color-success); }
    .cmp-rationale { color: var(--text-secondary); line-height: 1.5; }

    /* Assessments */
    .assessments-section { margin-bottom: var(--sp-4); }
    .asm-row { display: flex; gap: var(--sp-2); padding: var(--sp-2) 0; border-bottom: 1px solid var(--border); font-size: 0.75rem; align-items: flex-start; }
    .asm-row:last-child { border-bottom: none; }
    .asm-verdict { font-size: 0.5rem; font-family: var(--font-mono); font-weight: 700; padding: 2px 4px; border-radius: var(--radius-sm); flex-shrink: 0; }
    .verdict-supported { background: rgba(46,125,50,.15); color: var(--color-success); }
    .verdict-partially-supported { background: rgba(230,81,0,.15); color: var(--color-warning); }
    .verdict-not-supported { background: rgba(198,40,40,.15); color: var(--color-danger); }
    .verdict-not-verifiable { background: rgba(140,140,140,.15); color: var(--text-muted); }
    .asm-claim { color: var(--text-secondary); line-height: 1.5; }

    /* Citations tab */
    .cite-group { margin-bottom: var(--sp-4); }
    .cite-group-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--sp-2); }
    .cite-source-name { font-size: 0.6875rem; font-weight: 600; color: var(--accent); }
    .cite-count { font-size: 0.5625rem; background: var(--bg-canvas); border: 1px solid var(--border); border-radius: var(--radius-full); padding: 0 var(--sp-1); color: var(--text-muted); }
    .cite-item { display: flex; align-items: flex-start; gap: var(--sp-2); padding: var(--sp-1) 0; border-bottom: 1px solid rgba(0,0,0,.04); }
    .cite-item:last-child { border-bottom: none; }
    .cite-loc-badge { font-size: 0.5rem; background: rgba(27,111,107,.08); color: var(--accent); border-radius: var(--radius-sm); padding: 1px 4px; flex-shrink: 0; white-space: nowrap; }
    .cite-excerpt-text { font-size: 0.6875rem; color: var(--text-muted); font-style: italic; line-height: 1.5; }

    /* Audit tab */
    .conf-spark-section { margin-bottom: var(--sp-4); }
    .conf-spark { display: flex; align-items: flex-end; gap: 3px; height: 48px; }
    .spark-bar-wrap { display: flex; flex-direction: column; align-items: center; gap: 2px; flex: 1; height: 100%; justify-content: flex-end; }
    .spark-bar { width: 100%; border-radius: 2px 2px 0 0; min-height: 2px; transition: height var(--duration-md); }
    .spark-bar.conf-high { background: var(--color-success); }
    .spark-bar.conf-mid  { background: var(--color-warning); }
    .spark-bar.conf-low  { background: var(--color-danger); }
    .spark-label { font-size: 0.4375rem; color: var(--text-muted); }

    .audit-row { display: flex; align-items: baseline; gap: var(--sp-2); padding: var(--sp-1) 0; border-bottom: 1px solid rgba(0,0,0,.04); font-size: 0.6875rem; }
    .audit-row:last-child { border-bottom: none; }
    .audit-ts { font-size: 0.5rem; color: var(--text-muted); white-space: nowrap; }
    .audit-type { font-size: 0.5rem; font-weight: 600; padding: 1px 4px; border-radius: var(--radius-sm); }
    .atype-run_started   { background: rgba(27,111,107,.1); color: var(--accent); }
    .atype-plan_ready    { background: rgba(27,111,107,.1); color: var(--accent); }
    .atype-step_started  { background: rgba(45,90,142,.1); color: var(--color-prim); }
    .atype-step_finished { background: rgba(46,125,50,.1); color: var(--color-success); }
    .atype-human_review_req { background: rgba(230,81,0,.1); color: var(--color-warning); }
    .atype-run_finished  { background: rgba(46,125,50,.15); color: var(--color-success); }
    .atype-run_error     { background: rgba(198,40,40,.1); color: var(--color-danger); }
    .audit-detail { color: var(--text-muted); }

    /* Trace tab */
    .trace-meta { border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--sp-3); margin-bottom: var(--sp-4); }
    .trace-row { display: flex; justify-content: space-between; font-size: 0.75rem; padding: var(--sp-1) 0; border-bottom: 1px solid rgba(0,0,0,.04); }
    .trace-row:last-child { border-bottom: none; }
    .trace-key { color: var(--text-secondary); }
    .trace-val { font-weight: 500; }
    .trace-step { border: 1px solid var(--border); border-radius: var(--radius-md); margin-bottom: var(--sp-2); overflow: hidden; }
    .trace-step-header {
      display: flex; align-items: center; gap: var(--sp-2); width: 100%;
      padding: var(--sp-2) var(--sp-3); background: none; border: none; cursor: pointer;
      text-align: left; transition: background var(--duration-fast);
    }
    .trace-step-header:hover { background: var(--bg-canvas); }
    .ptype-mini { font-size: 0.4375rem; font-family: var(--font-mono); font-weight: 700; padding: 1px 3px; border-radius: var(--radius-sm); color: #fff; flex-shrink: 0; }
    .trace-step-name { font-size: 0.6875rem; font-weight: 600; }
    .trace-step-prim { font-size: 0.5625rem; color: var(--text-muted); flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .conf-mini { font-size: 0.625rem; font-family: var(--font-mono); font-weight: 600; }
    .trace-step-dur { font-size: 0.5625rem; color: var(--text-muted); }
    .expand-arrow { font-size: 0.5625rem; color: var(--text-muted); flex-shrink: 0; }
    .trace-step-body { padding: var(--sp-3); border-top: 1px solid var(--border); background: var(--bg-canvas); }
    .trace-section-label { font-size: 0.5rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; color: var(--text-muted); margin: var(--sp-2) 0 var(--sp-1); }
    .trace-json { font-size: 0.5625rem; font-family: var(--font-mono); white-space: pre-wrap; word-break: break-all; background: var(--bg-surface); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: var(--sp-2); max-height: 200px; overflow-y: auto; color: var(--text-secondary); }
    .trace-cite { display: flex; gap: var(--sp-2); font-size: 0.5625rem; padding: 2px 0; }
    .trace-issue { font-size: 0.5625rem; color: var(--color-warning); padding: 2px 0; }
    .llm-call { border: 1px solid var(--border); border-radius: var(--radius-sm); padding: var(--sp-2); margin-bottom: var(--sp-2); }
    .llm-call-meta { display: flex; gap: var(--sp-3); font-size: 0.5rem; color: var(--text-muted); margin-bottom: var(--sp-1); }
    .llm-prompt-preview, .llm-resp-preview { font-size: 0.5625rem; font-family: var(--font-mono); color: var(--text-muted); white-space: pre-wrap; word-break: break-all; max-height: 120px; overflow-y: auto; }
    .llm-resp-preview { color: var(--accent); }
    .err-text { color: var(--color-danger); }
  `],
})
export class ResultsPanelComponent {
  protected state = inject(RunStateService);
  private api = inject(ApiService);
  readonly activeTab = signal<Tab>('answer');
  readonly traceData = signal<Record<string, unknown> | null>(null);
  readonly traceLoading = signal(false);

  readonly tabs: {id: Tab; label: string}[] = [
    { id: 'answer', label: 'Answer' },
    { id: 'citations', label: 'Citations' },
    { id: 'audit', label: 'Audit' },
    { id: 'trace', label: 'Trace' },
  ];

  readonly allCitations = computed(() => {
    const cites: { source: string; location: string; excerpt: string }[] = [];
    for (const ev of this.state.events()) {
      if (ev.type === 'step_finished') {
        const raw = (ev.payload['citations'] as any[]) ?? [];
        for (const c of raw) {
          if (c && c.source) cites.push(c);
        }
      }
    }
    return cites;
  });

  readonly citationGroups = computed<CitationGroup[]>(() => {
    const groups: Record<string, CitationGroup> = {};
    for (const c of this.allCitations()) {
      if (!groups[c.source]) groups[c.source] = { source: c.source, items: [] };
      groups[c.source].items.push({ location: c.location, excerpt: c.excerpt });
    }
    return Object.values(groups);
  });

  readonly confScores = computed(() => {
    const scores: { primitive: string; confidence: number }[] = [];
    for (const ev of this.state.events()) {
      if (ev.type === 'step_finished') {
        scores.push({
          primitive: ev.payload['primitive'] as string,
          confidence: ev.payload['confidence'] as number ?? 0,
        });
      }
    }
    return scores;
  });

  verOk(v: unknown): boolean {
    return typeof v === 'object' && v !== null && (v as any)['ok'] === true;
  }

  verTotal(v: unknown): number {
    return (typeof v === 'object' && v !== null) ? ((v as any)['total'] ?? 0) : 0;
  }

  asArr(v: unknown): any[] { return Array.isArray(v) ? v : []; }

  fmtAnswer(v: unknown): string {
    if (typeof v === 'string') return v;
    if (v == null) return '';
    return JSON.stringify(v, null, 2);
  }

  // Answer type detection helpers
  waterfallSteps(answer: unknown): any[] {
    if (typeof answer === 'object' && answer !== null) {
      const steps = (answer as any)['waterfall_steps'];
      if (Array.isArray(steps) && steps.length > 0) return steps;
    }
    return [];
  }

  isStringAnswer(answer: unknown): boolean {
    return typeof answer === 'string' && answer.length > 0;
  }

  isGenericAnswer(answer: unknown): boolean {
    if (answer == null || typeof answer === 'string') return false;
    if (typeof answer !== 'object') return false;
    // It's an object but not a waterfall — show as JSON
    return this.waterfallSteps(answer).length === 0;
  }

  primTypeOf(name: string): string { return (name as string)?.split('.')[0] ?? ''; }
  primTypeLabel(name: string): string { return this.primTypeOf(name).slice(0,3).toUpperCase(); }

  truncate(s: string, n: number): string {
    return s && s.length > n ? s.slice(0, n) + '…' : (s ?? '');
  }

  confBarClass(c: number): string {
    if (c >= 0.8) return 'conf-high';
    if (c >= 0.5) return 'conf-mid';
    return 'conf-low';
  }

  fmtTs(iso: string): string {
    try {
      const d = new Date(iso);
      return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch { return ''; }
  }

  auditDetail(ev: any): string {
    const p = ev.payload;
    switch (ev.type) {
      case 'plan_ready': return `${p['step_count']} steps · ${p['source']}`;
      case 'step_started': return p['primitive'] ?? '';
      case 'step_finished': return `${p['primitive']} · conf ${(p['confidence'] ?? 0).toFixed(2)} · ${p['citations']?.length ?? 0} cites`;
      case 'human_review_req': return `${p['primitive']} · conf ${(p['confidence'] ?? 0).toFixed(2)} < ${p['floor']}`;
      case 'run_finished': return `${p['step_count']} steps complete`;
      case 'run_error': return p['message'] ?? 'error';
      default: return '';
    }
  }

  // ── Trace tab ──────────────────────────────────────────────────────────────
  readonly expandedStep = signal<string | null>(null);

  toggleStep(stepId: string): void {
    this.expandedStep.update(cur => cur === stepId ? null : stepId);
  }

  loadTrace(attempt = 0): void {
    const id = this.state.runId();
    if (!id) return;
    this.traceData.set(null);
    this.traceLoading.set(true);
    this.api.getTrace(id).subscribe({
      next: (data) => { this.traceData.set(data); this.traceLoading.set(false); },
      error: (err) => {
        // Trace file may not be written yet — retry up to 3 times with backoff
        if (err?.status === 404 && attempt < 3) {
          setTimeout(() => this.loadTrace(attempt + 1), 1500);
        } else {
          this.traceLoading.set(false);
        }
      },
    });
  }

  selectTab(tab: Tab): void {
    this.activeTab.set(tab);
    if (tab === 'trace' && this.state.phase() === 'done') {
      this.loadTrace();
    }
  }

  confClass(c: unknown): string {
    const n = typeof c === 'number' ? c : 0;
    if (n >= 0.8) return 'conf-val conf-high';
    if (n >= 0.5) return 'conf-val conf-mid';
    return 'conf-val conf-low';
  }
  fmtMs(ms: unknown): string {
    const n = typeof ms === 'number' ? ms : 0;
    return n < 1000 ? `${n.toFixed(0)}ms` : `${(n/1000).toFixed(1)}s`;
  }
  fmtJson(v: unknown): string {
    try { return JSON.stringify(v, null, 2); } catch { return String(v); }
  }
}
