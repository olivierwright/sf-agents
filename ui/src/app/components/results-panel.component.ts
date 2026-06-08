import {
  Component,
  inject,
  signal,
  computed,
  ChangeDetectionStrategy,
  effect,
  HostBinding,
  ViewChild,
} from '@angular/core';
import { RunStateService } from '../services/run-state.service';
import { ApiService } from '../services/api.service';
import { DashboardPanelComponent } from './dashboard-panel.component';
import { LodResultsComponent } from './lod-results.component';
import { DagFlowComponent } from './dag-flow.component';
import { BenchmarkViewComponent } from './benchmark-view.component';
import { AuditDrawerComponent } from './audit-drawer.component';
import { MarkdownPipe } from '../pipes/markdown.pipe';

type Tab = 'answer' | 'citations' | 'audit' | 'plan' | 'trace' | 'dashboard' | 'lod' | 'benchmark';

interface CitationGroup {
  source: string;
  items: { location: string; excerpt: string }[];
}

@Component({
  selector: 'app-results-panel',
  standalone: true,
  imports: [DashboardPanelComponent, LodResultsComponent, DagFlowComponent, BenchmarkViewComponent, AuditDrawerComponent, MarkdownPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="results-panel" [class.expanded]="expanded()">
      <!-- Tab bar -->
      <div class="tab-bar">
        @for (tab of visibleTabs(); track tab.id) {
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
        <div class="tab-bar-actions">
          @if (activeTab() === 'dashboard') {
            <button class="icon-btn" (click)="toggleExpand()" [title]="expanded() ? 'Collapse' : 'Expand dashboard'">
              {{ expanded() ? '⊟' : '⊞' }}
            </button>
          }
          @if (state.runId() && state.phase() === 'done') {
            <button class="icon-btn audit-btn" (click)="openAuditDrawer()" title="Open audit trail">
              ⛭
            </button>
          }
        </div>
      </div>

      <div class="panel-body">

        <!-- ── ANSWER TAB ──────────────────────── -->
        @if (activeTab() === 'answer') {
          <div class="tab-content answer-tab">

            @if (state.phase() === 'idle') {
              <div class="panel-empty">
                <span class="panel-empty-icon">◎</span>
                <p>Results will appear here when the analysis completes.</p>
              </div>

            } @else if (state.phase() === 'planning' || state.phase() === 'executing' || (state.phase() === 'verifying' && !state.result())) {
              <!-- Skeleton loader that fills the space -->
              <div class="chat-skeleton">
                <!-- "User" bubble skeleton -->
                <div class="skel-user">
                  <div class="skel-bar skel-bar-sm" style="width:60%;animation-delay:0ms"></div>
                </div>
                <!-- "Agent" response skeleton -->
                <div class="skel-agent">
                  <div class="skel-agent-header">
                    <div class="skel-dot"></div>
                    <div class="skel-bar skel-bar-xs" style="width:80px"></div>
                  </div>
                  <div class="skel-body">
                    @for (i of [90,75,100,65,88,72,95,60]; track i) {
                      <div class="skel-bar" [style.width.%]="i" [style.animation-delay.ms]="i * 15"></div>
                    }
                    <div class="skel-bar skel-bar-sm" style="width:45%;animation-delay:500ms"></div>
                  </div>
                </div>
                <p class="skel-status">
                  {{ state.phase() === 'verifying' ? 'Synthesising answer…' : state.phase() === 'planning' ? 'Planning…' : 'Executing ' + state.completedSteps() + '/' + state.totalSteps() + ' steps…' }}
                </p>
              </div>

            } @else if (state.phase() === 'waiting_for_input') {
              <div class="panel-loading"><p class="loading-label">Paused — awaiting analyst input…</p></div>

            } @else if (state.phase() === 'error') {
              <div class="error-card" style="margin:var(--sp-4)">
                <span class="err-icon">✕</span>
                <span>{{ state.error() ?? 'Run failed' }}</span>
              </div>

            } @else if (state.result(); as result) {
              <div class="chat-thread">

                <!-- USER MESSAGE -->
                <div class="msg-user" style="animation-delay:0ms">
                  <div class="msg-user-text">{{ state.activeQuestion() }}</div>
                  <div class="msg-user-meta">
                    <span class="meta-chip">{{ state.activeStrategy() }}</span>
                    @if (result['lod_citation_note']) {
                      <span class="meta-chip meta-chip-purple">⬡ synthesised</span>
                    }
                  </div>
                </div>

                <!-- AGENT RESPONSE CARD -->
                <div class="msg-agent" style="animation-delay:80ms">

                  <!-- Agent header bar -->
                  <div class="agent-header-bar">
                    <div class="agent-id">
                      <span class="agent-dot"></span>
                      <span class="agent-label">SF Agent</span>
                    </div>
                    <div class="agent-meta-right">
                      @if (result['verification']) {
                        <span class="ver-badge" [class.ok]="verOk(result['verification'])">
                          {{ verOk(result['verification']) ? '✓' : '⚠' }}
                          {{ verTotal(result['verification']) }} citations
                        </span>
                      }
                      <!-- Collapsible plan trigger -->
                      @if (result['plan']) {
                        <button class="plan-pill" (click)="planOpen.update(v => !v)">
                          {{ planOpen() ? '▾' : '▸' }}
                          {{ asArr(planSteps(result['plan'])).length }}-step plan
                        </button>
                      }
                    </div>
                  </div>

                  <!-- Inline plan DAG (collapsible) -->
                  @if (planOpen() && state.dag().length > 0) {
                    <div class="agent-plan-dag">
                      <app-dag-flow [steps]="state.dag()" />
                    </div>
                  }

                  <!-- Human review warning (inside card) -->
                  @if (asArr(result['review_queue']).length > 0) {
                    <div class="agent-review-banner">
                      <span>⚠</span>
                      {{ asArr(result['review_queue']).length }} step(s) flagged for human review
                      — treat output with care.
                    </div>
                  }

                  <!-- THE ANSWER — this is the hero -->
                  <div class="agent-body">

                    @if (isStringAnswer(result['answer'])) {
                      <div class="answer-markdown" [innerHTML]="asString(result['answer']) | markdown"></div>
                    }

                    @if (waterfallSteps(result['answer']).length > 0) {
                      <div class="wf-section">
                        <div class="wf-title">Priority of Payments — {{ waterfallSteps(result['answer']).length }} steps</div>
                        @for (step of waterfallSteps(result['answer']); track step['rank']) {
                          <div class="waterfall-row">
                            <div class="wf-rank">{{ step['rank'] }}</div>
                            <div class="wf-body">
                              <div class="wf-beneficiary">{{ step['beneficiary'] }}</div>
                              <div class="wf-basis">{{ step['amount_basis'] }}</div>
                              @if (step['conditions'] && step['conditions'] !== 'none') {
                                <div class="wf-conditions">⚑ {{ step['conditions'] }}</div>
                              }
                            </div>
                            <div class="wf-page mono">p.{{ step['page'] }}</div>
                          </div>
                        }
                      </div>
                    }

                    @if (isGenericAnswer(result['answer'])) {
                      <pre class="answer-json">{{ fmtAnswer(result['answer']) }}</pre>
                    }

                    @if (!result['answer'] && !result['comparisons'] && !result['assessments'] && waterfallSteps(result['answer']).length === 0) {
                      <p class="loading-label" style="padding:0">Loading answer…</p>
                    }

                    <!-- Definition comparisons inline -->
                    @if (asArr(result['comparisons']).length > 0) {
                      <div class="inline-section">
                        <div class="inline-section-title">Definition comparison</div>
                        @for (cmp of asArr(result['comparisons']); track cmp['term']) {
                          <div class="cmp-row">
                            <div class="cmp-term">{{ cmp['term'] }}</div>
                            <div class="cmp-mat-badge" [class]="'mat-' + cmp['materiality']">{{ cmp['materiality'] }}</div>
                            <div class="cmp-rationale">{{ cmp['rationale'] }}</div>
                          </div>
                        }
                      </div>
                    }

                    <!-- Impact assessments inline -->
                    @if (asArr(result['assessments']).length > 0) {
                      <div class="inline-section">
                        <div class="inline-section-title">Green claims vs. collateral</div>
                        @for (a of asArr(result['assessments']); track a['claim']) {
                          <div class="asm-card">
                            <div class="asm-card-header">
                              <div class="asm-verdict" [class]="'verdict-' + slugVerdict(a['verdict'])">{{ a['verdict'] }}</div>
                              <div class="asm-claim">{{ truncate(a['claim'], 110) }}</div>
                            </div>
                            @if (a['rationale']) {
                              <div class="asm-rationale">{{ a['rationale'] }}</div>
                            }
                            <div class="asm-grounding">
                              <div class="asm-ground-col">
                                <span class="ground-icon">📋</span>
                                <span class="ground-text">{{ a['claim_source'] }}{{ a['claim_page'] != null ? ' p.' + a['claim_page'] : '' }}</span>
                              </div>
                              <div class="asm-ground-sep"></div>
                              <div class="asm-ground-col">
                                <span class="ground-icon">📊</span>
                                <span class="ground-text">{{ (a['tape_columns'] ?? []).join(', ') || 'tape' }}</span>
                              </div>
                            </div>
                          </div>
                        }
                      </div>
                    }

                    <!-- IC verdict (3LoD) -->
                    @if (result['consolidated_verdict']) {
                      <div class="ic-verdict-block">
                        <div class="ic-verdict-label">Investment Committee</div>
                        <div class="ic-verdict-text">{{ result['consolidated_verdict'] }}</div>
                      </div>
                    }

                    <!-- Clarifications thread -->
                    @if (asArr(result['clarifications']).length > 0) {
                      <div class="clar-thread">
                        @for (c of asArr(result['clarifications']); track c['step_id']) {
                          <div class="clar-q">🤔 {{ c['question'] }}</div>
                          <div class="clar-a">↳ {{ c['answer'] }}</div>
                        }
                      </div>
                    }

                  </div><!-- /agent-body -->

                  <!-- Footer strip -->
                  <div class="agent-footer">
                    <span class="footer-stat mono">{{ state.completedSteps() }} steps</span>
                    <span class="footer-dot">·</span>
                    <span class="footer-stat mono">{{ allCitations().length }} citations</span>
                    <span class="footer-dot">·</span>
                    <span class="footer-stat mono">{{ fmtMs(state.elapsedMs()) }}</span>
                  </div>

                </div><!-- /msg-agent -->

              </div><!-- /chat-thread -->
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
                      <span class="cite-loc-badge mono" [class]="citeLocClass(item.location)">
                        {{ item.location }}
                      </span>
                      <span class="cite-excerpt-text">"{{ truncate(item.excerpt, 120) }}"</span>
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

        <!-- ── PLAN TAB ──────────────────────── -->
        @if (activeTab() === 'plan') {
          <div class="tab-content">
            @if (state.dag().length === 0) {
              <div class="panel-empty">
                <span class="panel-empty-icon">⬡</span>
                <p>The execution plan will appear here after planning completes.</p>
              </div>
            } @else {
              <div class="plan-explanation">
                {{ state.planExplanation() }}
              </div>
              <app-dag-flow [steps]="state.dag()" />
            }
          </div>
        }

        <!-- ── DASHBOARD TAB ─────────────────── -->
        @if (activeTab() === 'dashboard') {
          <app-dashboard-panel />
        }

        <!-- ── 3LOD TAB ──────────────────────── -->
        @if (activeTab() === 'lod') {
          <app-lod-results [steps]="state.steps()" [lodOutputs]="state.lodAgentOutputs()" />
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
                  @for (i of [1, 2, 3]; track i) {
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
                <div class="trace-row"><span class="trace-key">Duration</span><span class="trace-val mono">{{ fmtMs(traceData()!['duration_ms']) }}</span></div>
                <div class="trace-row"><span class="trace-key">Strategy</span><span class="trace-val mono">{{ traceData()!['strategy'] }}</span></div>
                <div class="trace-row"><span class="trace-key">Steps</span><span class="trace-val mono">{{ asArr(traceData()!['steps']).length }}</span></div>
              </div>
              <div class="sec-label" style="margin-top: var(--sp-4)">STEP DETAILS</div>
              @for (step of asArr(traceData()!['steps']); track step['step_id']) {
                <div class="trace-step" [class.expanded]="expandedStep() === step['step_id']">
                  <button class="trace-step-header" (click)="toggleStep(step['step_id'])">
                    <span class="ptype-mini" [class]="'ptype-' + primTypeOf(step['primitive'])">{{ primTypeLabel(step['primitive']) }}</span>
                    <span class="trace-step-name mono">{{ step['step_id'] }}</span>
                    <span class="trace-step-prim">{{ step['primitive'] }}</span>
                    <span class="conf-mini" [class]="confClass(step['output']?.['confidence'])">{{ (step['output']?.['confidence'] ?? 0).toFixed(2) }}</span>
                    <span class="trace-step-dur mono">{{ fmtMs(step['duration_ms']) }}</span>
                    <span class="expand-arrow">{{ expandedStep() === step['step_id'] ? '▾' : '▸' }}</span>
                  </button>
                  @if (expandedStep() === step['step_id']) {
                    <div class="trace-step-body">
                      <div class="trace-section-label">INPUTS</div>
                      <pre class="trace-json">{{ fmtJson(step['input_args']) }}</pre>
                      <div class="trace-section-label">OUTPUT</div>
                      <pre class="trace-json">{{ fmtJson(step['output']?.['payload']) }}</pre>
                      @if (asArr(step['output']?.['citations']).length > 0) {
                        <div class="trace-section-label">CITATIONS ({{ asArr(step['output']?.['citations']).length }})</div>
                        @for (c of asArr(step['output']?.['citations']); track c['location']) {
                          <div class="trace-cite">
                            <span class="cite-loc-badge mono">{{ c['location'] }}</span>
                            <span class="cite-excerpt-text">"{{ truncate(c['excerpt'], 80) }}"</span>
                          </div>
                        }
                      }
                      @if (asArr(step['output']?.['issues']).length > 0) {
                        <div class="trace-section-label">ISSUES</div>
                        @for (issue of asArr(step['output']?.['issues']); track issue) {
                          <div class="trace-issue">⚠ {{ issue }}</div>
                        }
                      }
                      @if (asArr(step['llm_calls']).length > 0) {
                        <div class="trace-section-label">LLM CALLS ({{ asArr(step['llm_calls']).length }})</div>
                        @for (call of asArr(step['llm_calls']); track call['seq']) {
                          <div class="llm-call">
                            <div class="llm-call-meta">
                              <span class="mono">prompt {{ call['prompt_chars'] }} chars</span>
                              <span class="mono">response {{ call['response_chars'] }} chars</span>
                              <span [class.ok-text]="call['parsed_ok']" [class.err-text]="!call['parsed_ok']">{{ call['parsed_ok'] ? '✓ parsed' : '✕ failed' }}</span>
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

        <!-- ── BENCHMARK TAB ─────────────────── -->
        @if (activeTab() === 'benchmark') {
          <div class="tab-content benchmark-tab">
            @if (benchmarkRuns().length === 0) {
              <div class="panel-empty">
                <span class="panel-empty-icon">⚡</span>
                <p>Run a benchmark to compare strategies side-by-side.</p>
                <button class="btn-benchmark" (click)="runBenchmark()" [disabled]="!canBenchmark()">
                  Run Benchmark
                </button>
              </div>
            } @else {
              <app-benchmark-view [runs]="benchmarkRuns()" />
            }
          </div>
        }

      </div>
    </div>

    <!-- Audit drawer — outside the panel so it overlays the whole UI -->
    <app-audit-drawer #auditDrawer />
  `,
  styles: [
    `
      .results-panel {
        width: 600px;
        min-width: 560px;
        height: 100%;
        border-left: 1px solid var(--border);
        background: var(--bg-canvas);
        display: flex;
        flex-direction: column;
        overflow: hidden;
        transition: all 0.3s ease;
      }
      .results-panel.expanded {
        position: fixed;
        inset: 0;
        z-index: 1000;
        width: 100vw;
        min-width: 100vw;
        height: 100vh;
        border-left: none;
        border-radius: 0;
      }

      /* Tab bar */
      .tab-bar {
        display: flex;
        border-bottom: 1px solid var(--border);
        flex-shrink: 0;
        align-items: stretch;
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
        font-size: 0.6875rem;
        font-weight: 500;
        color: var(--text-muted);
        transition: all var(--duration-fast);
      }
      .tab-btn.active {
        color: var(--accent);
        border-bottom-color: var(--accent);
      }
      .tab-btn:hover:not(.active) { color: var(--text-secondary); }
      .tab-count {
        background: var(--bg-canvas);
        border: 1px solid var(--border);
        border-radius: var(--radius-full);
        padding: 0 var(--sp-1);
        font-size: 0.5rem;
        font-family: var(--font-mono);
        color: var(--text-muted);
      }
      .tab-bar-actions {
        display: flex;
        align-items: center;
        gap: 2px;
        padding: 0 var(--sp-2);
        border-left: 1px solid var(--border);
        flex-shrink: 0;
      }
      .icon-btn {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 28px;
        background: none;
        border: none;
        border-radius: var(--radius-sm);
        cursor: pointer;
        font-size: 0.875rem;
        color: var(--text-muted);
        transition: all var(--duration-fast);
      }
      .icon-btn:hover { color: var(--accent); background: rgba(27, 111, 107, 0.08); }
      .audit-btn { font-size: 0.75rem; }

      /* Panel body */
      .panel-body { flex: 1; overflow-y: auto; }
      .tab-content { padding: var(--sp-4); }
      .answer-tab { padding: 0; background: var(--bg-canvas); }

      /* Empty / loading states */
      .panel-empty {
        display: flex; flex-direction: column; align-items: center;
        gap: var(--sp-3); padding: var(--sp-12) var(--sp-4); text-align: center;
      }
      .panel-empty-icon { font-size: 2rem; opacity: 0.3; }
      .panel-empty p { font-size: 0.8125rem; color: var(--text-muted); }
      .panel-loading { padding: var(--sp-4); }
      .loading-steps { display: flex; flex-direction: column; gap: var(--sp-2); margin-bottom: var(--sp-4); }
      .loading-row { animation: loadingPulse 1.4s ease-in-out infinite; }
      .loading-bar { height: 8px; background: var(--border); border-radius: 4px; }
      @keyframes loadingPulse {
        0%, 100% { opacity: 0.4; }
        50% { opacity: 1; }
      }
      .loading-label { font-size: 0.75rem; color: var(--text-muted); text-align: center; }
      .error-card {
        display: flex; gap: var(--sp-2); padding: var(--sp-4);
        background: rgba(198,40,40,0.06); border: 1px solid rgba(198,40,40,0.2);
        border-radius: var(--radius-md); color: var(--color-danger); font-size: 0.8125rem;
      }
      .err-icon { font-size: 1rem; }

      /* ── SKELETON LOADER ── */
      .chat-skeleton {
        padding: var(--sp-5) var(--sp-5) var(--sp-4);
        display: flex; flex-direction: column; gap: var(--sp-4);
      }
      .skel-user {
        align-self: flex-end;
        background: rgba(27,111,107,0.06); border-radius: var(--radius-lg) var(--radius-sm) var(--radius-lg) var(--radius-lg);
        padding: var(--sp-3) var(--sp-4); width: 70%;
      }
      .skel-agent { display: flex; flex-direction: column; gap: var(--sp-3); }
      .skel-agent-header { display: flex; align-items: center; gap: var(--sp-2); margin-bottom: var(--sp-1); }
      .skel-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--border); animation: loadingPulse 1.4s ease-in-out infinite; }
      .skel-body {
        background: var(--bg-surface); border-radius: var(--radius-lg);
        padding: var(--sp-5); display: flex; flex-direction: column; gap: var(--sp-3);
        box-shadow: var(--shadow-sm); border: 1px solid var(--border);
      }
      .skel-bar {
        height: 12px; background: var(--border); border-radius: 6px;
        animation: loadingPulse 1.4s ease-in-out infinite;
      }
      .skel-bar-sm { height: 10px; }
      .skel-bar-xs { height: 8px; }
      .skel-status { font-size: 0.6875rem; color: var(--text-muted); text-align: center; padding-top: var(--sp-2); }

      /* ── CHAT THREAD ── */
      .chat-thread {
        padding: var(--sp-5) var(--sp-5) var(--sp-6);
        display: flex;
        flex-direction: column;
        gap: var(--sp-4);
      }

      /* User message */
      @keyframes msgIn {
        from { opacity: 0; transform: translateY(16px); }
        to   { opacity: 1; transform: translateY(0); }
      }

      .msg-user {
        align-self: flex-end;
        background: rgba(27, 111, 107, 0.08);
        border: 1px solid rgba(27, 111, 107, 0.15);
        border-radius: var(--radius-xl) var(--radius-sm) var(--radius-xl) var(--radius-xl);
        padding: var(--sp-3) var(--sp-4);
        max-width: 85%;
        animation: msgIn 300ms var(--ease-out) both;
      }
      .msg-user-text {
        font-size: 0.875rem;
        color: var(--text-primary);
        line-height: 1.55;
        font-style: italic;
        margin-bottom: var(--sp-2);
      }
      .msg-user-meta { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; }
      .meta-chip {
        font-size: 0.5rem; font-family: var(--font-mono);
        background: rgba(27,111,107,0.1); color: var(--accent);
        border-radius: var(--radius-full); padding: 1px var(--sp-2);
      }
      .meta-chip-purple {
        background: rgba(123,94,167,0.1); color: var(--color-agent);
      }

      /* Agent response card */
      .msg-agent {
        background: var(--bg-surface);
        border: 1px solid var(--border);
        border-radius: var(--radius-sm) var(--radius-xl) var(--radius-xl) var(--radius-xl);
        box-shadow: var(--shadow-md);
        overflow: hidden;
        animation: msgIn 400ms 80ms var(--ease-out) both;
      }

      /* Agent header bar */
      .agent-header-bar {
        display: flex; align-items: center; justify-content: space-between;
        padding: var(--sp-3) var(--sp-4);
        border-bottom: 1px solid var(--border);
        background: var(--bg-canvas);
      }
      .agent-id { display: flex; align-items: center; gap: var(--sp-2); }
      .agent-dot {
        width: 7px; height: 7px; border-radius: 50%;
        background: var(--accent);
        box-shadow: 0 0 0 2px rgba(27,111,107,0.2);
      }
      .agent-label {
        font-size: 0.6875rem; font-weight: 600;
        color: var(--text-secondary); letter-spacing: 0.02em;
      }
      .agent-meta-right { display: flex; align-items: center; gap: var(--sp-2); }
      .ver-badge {
        font-size: 0.5625rem; font-family: var(--font-mono);
        padding: 2px var(--sp-2); border-radius: var(--radius-full);
        background: rgba(198,40,40,0.08); color: var(--color-danger);
      }
      .ver-badge.ok { background: rgba(46,125,50,0.08); color: var(--color-success); }
      .plan-pill {
        font-size: 0.5625rem; font-family: var(--font-mono);
        background: none; border: 1px solid var(--border);
        border-radius: var(--radius-full); padding: 2px var(--sp-2);
        cursor: pointer; color: var(--text-muted);
        transition: all var(--duration-fast);
      }
      .plan-pill:hover { border-color: var(--accent); color: var(--accent); }

      /* Plan DAG inside card */
      .agent-plan-dag {
        padding: var(--sp-3) var(--sp-4);
        background: var(--bg-canvas);
        border-bottom: 1px solid var(--border);
      }

      /* Review banner */
      .agent-review-banner {
        display: flex; align-items: center; gap: var(--sp-2);
        padding: var(--sp-2) var(--sp-4);
        background: rgba(230,81,0,0.06); border-bottom: 1px solid rgba(230,81,0,0.2);
        font-size: 0.75rem; color: var(--color-warning);
      }

      /* The answer body */
      .agent-body {
        padding: var(--sp-5) var(--sp-5) var(--sp-4);
      }

      /* Answer JSON fallback */
      .answer-json {
        font-size: 0.5625rem; font-family: var(--font-mono); white-space: pre-wrap;
        word-break: break-all; background: var(--bg-canvas); border: 1px solid var(--border);
        border-radius: var(--radius-sm); padding: var(--sp-3); max-height: 300px; overflow-y: auto;
        color: var(--text-secondary); margin: 0;
      }

      /* Waterfall inside card */
      .wf-section { margin-top: var(--sp-4); }
      .wf-title { font-size: 0.6875rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: var(--sp-3); }
      .waterfall-row {
        display: grid; grid-template-columns: 24px 1fr 32px;
        gap: var(--sp-3); padding: var(--sp-2) 0;
        border-bottom: 1px solid var(--border); align-items: flex-start;
      }
      .waterfall-row:last-child { border-bottom: none; }
      .wf-rank { width: 24px; height: 24px; border-radius: 50%; background: var(--accent); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 0.5625rem; font-weight: 700; flex-shrink: 0; }
      .wf-body { display: flex; flex-direction: column; gap: 2px; }
      .wf-beneficiary { font-size: 0.8125rem; font-weight: 600; color: var(--text-primary); }
      .wf-basis { font-size: 0.6875rem; color: var(--text-secondary); line-height: 1.4; }
      .wf-conditions { font-size: 0.5625rem; color: var(--color-warning); }
      .wf-page { font-size: 0.5625rem; color: var(--text-muted); padding-top: 4px; }

      /* Inline sections (comparisons, assessments) */
      .inline-section { margin-top: var(--sp-5); }
      .inline-section-title {
        font-size: 0.6875rem; font-weight: 600; color: var(--text-muted);
        text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: var(--sp-3);
        padding-bottom: var(--sp-2); border-bottom: 1px solid var(--border);
      }

      /* Definition comparisons */
      .cmp-row {
        display: grid; grid-template-columns: 80px 80px 1fr; gap: var(--sp-2);
        padding: var(--sp-2) 0; border-bottom: 1px solid var(--border); align-items: start;
      }
      .cmp-row:last-child { border-bottom: none; }
      .cmp-term { font-weight: 600; color: var(--accent); font-size: 0.75rem; }
      .cmp-mat-badge { font-size: 0.5rem; font-family: var(--font-mono); font-weight: 700; padding: 2px 4px; border-radius: var(--radius-sm); }
      .mat-material { background: rgba(198,40,40,0.15); color: var(--color-danger); }
      .mat-moderate { background: rgba(230,81,0,0.15); color: var(--color-warning); }
      .mat-none { background: rgba(46,125,50,0.1); color: var(--color-success); }
      .cmp-rationale { color: var(--text-secondary); line-height: 1.5; font-size: 0.8125rem; }

      /* Impact assessment cards */
      .asm-card { border: 1px solid var(--border); border-radius: var(--radius-md); margin-bottom: var(--sp-2); overflow: hidden; }
      .asm-card-header { display: flex; align-items: flex-start; gap: var(--sp-2); padding: var(--sp-3); }
      .asm-verdict { font-size: 0.5rem; font-family: var(--font-mono); font-weight: 700; padding: 4px 8px; border-radius: var(--radius-sm); flex-shrink: 0; text-transform: uppercase; letter-spacing: 0.05em; }
      .verdict-supported { background: rgba(46,125,50,0.15); color: var(--color-success); }
      .verdict-partially-supported { background: rgba(230,81,0,0.15); color: var(--color-warning); }
      .verdict-not-supported { background: rgba(198,40,40,0.15); color: var(--color-danger); }
      .verdict-not-verifiable { background: rgba(140,140,140,0.15); color: var(--text-muted); }
      .asm-claim { font-size: 0.8125rem; color: var(--text-primary); line-height: 1.5; font-weight: 500; }
      .asm-rationale { font-size: 0.8125rem; color: var(--text-secondary); padding: 0 var(--sp-3) var(--sp-2); line-height: 1.55; }
      .asm-grounding { display: flex; align-items: center; padding: var(--sp-2) var(--sp-3); gap: var(--sp-2); background: var(--bg-canvas); border-top: 1px solid var(--border); }
      .asm-ground-col { display: flex; align-items: center; gap: var(--sp-2); flex: 1; }
      .asm-ground-sep { width: 1px; height: 20px; background: var(--border); flex-shrink: 0; }
      .ground-icon { font-size: 0.75rem; flex-shrink: 0; }
      .ground-text { font-size: 0.625rem; color: var(--text-muted); font-family: var(--font-mono); }

      /* IC Verdict */
      .ic-verdict-block {
        margin-top: var(--sp-4);
        background: rgba(27,111,107,0.04);
        border: 1px solid rgba(27,111,107,0.18);
        border-radius: var(--radius-md);
        padding: var(--sp-4);
      }
      .ic-verdict-label {
        font-size: 0.5rem; font-weight: 700; letter-spacing: 0.12em;
        text-transform: uppercase; color: var(--accent); margin-bottom: var(--sp-2);
      }
      .ic-verdict-text { font-size: 0.9rem; color: var(--text-primary); line-height: 1.7; }

      /* Clarification thread inside card */
      .clar-thread { margin-top: var(--sp-4); border-top: 1px dashed var(--border); padding-top: var(--sp-3); }
      .clar-q { font-size: 0.8125rem; color: var(--text-secondary); font-style: italic; margin-bottom: var(--sp-1); }
      .clar-a { font-size: 0.8125rem; color: var(--text-primary); padding-left: var(--sp-4); margin-bottom: var(--sp-2); }

      /* Agent footer */
      .agent-footer {
        display: flex; align-items: center; gap: var(--sp-2);
        padding: var(--sp-3) var(--sp-5);
        border-top: 1px solid var(--border);
        background: var(--bg-canvas);
      }
      .footer-stat { font-size: 0.5625rem; color: var(--text-muted); }
      .footer-dot { color: var(--border-strong); font-size: 0.5rem; }

      /* Section labels */
      .sec-label {
        font-size: 0.5rem; font-weight: 700; letter-spacing: 0.12em;
        text-transform: uppercase; color: var(--text-muted); margin-bottom: var(--sp-3);
      }

      /* Citations tab */
      .cite-group { margin-bottom: var(--sp-4); }
      .cite-group-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--sp-2); }
      .cite-source-name { font-size: 0.6875rem; font-weight: 600; color: var(--accent); }
      .cite-count { font-size: 0.5625rem; background: var(--bg-canvas); border: 1px solid var(--border); border-radius: var(--radius-full); padding: 0 var(--sp-1); color: var(--text-muted); }
      .cite-item { display: flex; align-items: flex-start; gap: var(--sp-2); padding: var(--sp-1) 0; border-bottom: 1px solid rgba(0,0,0,.04); }
      .cite-item:last-child { border-bottom: none; }
      .cite-loc-badge { font-size: 0.5rem; border-radius: var(--radius-sm); padding: 1px 4px; flex-shrink: 0; white-space: nowrap; background: rgba(27,111,107,0.08); color: var(--accent); }
      .cite-loc-badge.tape { background: rgba(123,94,167,0.1); color: var(--color-agent); }
      .cite-excerpt-text { font-size: 0.6875rem; color: var(--text-muted); font-style: italic; line-height: 1.5; }

      /* Audit tab */
      .conf-spark-section { margin-bottom: var(--sp-4); }
      .conf-spark { display: flex; align-items: flex-end; gap: 3px; height: 48px; }
      .spark-bar-wrap { display: flex; flex-direction: column; align-items: center; gap: 2px; flex: 1; height: 100%; justify-content: flex-end; }
      .spark-bar { width: 100%; border-radius: 2px 2px 0 0; min-height: 2px; transition: height var(--duration-md); }
      .spark-bar.conf-high { background: var(--color-success); }
      .spark-bar.conf-mid { background: var(--color-warning); }
      .spark-bar.conf-low { background: var(--color-danger); }
      .spark-label { font-size: 0.4375rem; color: var(--text-muted); }
      .audit-row { display: flex; align-items: baseline; gap: var(--sp-2); padding: var(--sp-1) 0; border-bottom: 1px solid rgba(0,0,0,.04); font-size: 0.6875rem; }
      .audit-row:last-child { border-bottom: none; }
      .audit-ts { font-size: 0.5rem; color: var(--text-muted); white-space: nowrap; }
      .audit-type { font-size: 0.5rem; font-weight: 600; padding: 1px 4px; border-radius: var(--radius-sm); }
      .atype-run_started, .atype-plan_ready { background: rgba(27,111,107,0.1); color: var(--accent); }
      .atype-step_started { background: rgba(45,90,142,0.1); color: var(--color-prim); }
      .atype-step_finished { background: rgba(46,125,50,0.1); color: var(--color-success); }
      .atype-human_review_req { background: rgba(230,81,0,0.1); color: var(--color-warning); }
      .atype-run_finished { background: rgba(46,125,50,0.15); color: var(--color-success); }
      .atype-run_error { background: rgba(198,40,40,0.1); color: var(--color-danger); }
      .audit-detail { color: var(--text-muted); }

      /* Plan tab */
      .plan-explanation {
        font-size: 0.8125rem; color: var(--text-secondary); line-height: 1.55;
        padding: var(--sp-3); background: var(--bg-canvas);
        border-radius: var(--radius-sm); margin-bottom: var(--sp-3);
        border-left: 3px solid var(--accent);
      }

      /* Trace tab */
      .trace-meta { border: 1px solid var(--border); border-radius: var(--radius-md); padding: var(--sp-3); margin-bottom: var(--sp-4); }
      .trace-row { display: flex; justify-content: space-between; font-size: 0.75rem; padding: var(--sp-1) 0; border-bottom: 1px solid rgba(0,0,0,.04); }
      .trace-row:last-child { border-bottom: none; }
      .trace-key { color: var(--text-secondary); }
      .trace-val { font-weight: 500; }
      .trace-step { border: 1px solid var(--border); border-radius: var(--radius-md); margin-bottom: var(--sp-2); overflow: hidden; }
      .trace-step-header { display: flex; align-items: center; gap: var(--sp-2); width: 100%; padding: var(--sp-2) var(--sp-3); background: none; border: none; cursor: pointer; text-align: left; transition: background var(--duration-fast); }
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
      .ok-text { color: var(--color-success); }

      /* Benchmark tab */
      .benchmark-tab {}
      .btn-benchmark {
        margin-top: var(--sp-4); padding: var(--sp-2) var(--sp-6); background: var(--accent); color: #fff;
        border: none; border-radius: var(--radius-md); cursor: pointer; font-size: 0.875rem;
        font-weight: 500;
      }
      .btn-benchmark:hover:not([disabled]) { opacity: 0.9; }
      .btn-benchmark[disabled] { opacity: 0.4; cursor: not-allowed; }

      /* Primitive type colours */
      .ptype-connector { background: var(--color-prim) !important; }
      .ptype-extractor { background: var(--accent) !important; }
      .ptype-analyzer  { background: var(--color-agent) !important; }
      .ptype-validator { background: var(--color-success) !important; }
      .ptype-formatter { background: #7B5EA7 !important; }
      .ptype-executor  { background: #E65100 !important; }
      .ptype-lod       { background: #2D5A8E !important; }

      /* Conf colours */
      .conf-high { color: var(--color-success); }
      .conf-mid  { color: var(--color-warning); }
      .conf-low  { color: var(--color-danger); }
    `,
  ],
})
export class ResultsPanelComponent {
  protected state = inject(RunStateService);
  private api = inject(ApiService);
  readonly activeTab = signal<Tab>('answer');
  readonly expanded = signal(false);
  readonly traceData = signal<Record<string, unknown> | null>(null);
  readonly traceLoading = signal(false);
  readonly planOpen = signal(false);
  readonly benchmarkRuns = signal<any[]>([]);

  @ViewChild('auditDrawer') auditDrawer!: AuditDrawerComponent;

  constructor() {
    effect(() => {
      const phase = this.state.phase();
      if (phase === 'done' && this.activeTab() === 'trace' && !this.traceData() && !this.traceLoading()) {
        this.loadTrace();
      }
      // Auto-switch to 3LoD tab when a 3LoD run completes
      if (phase === 'done' && this.state.activeRecipe() === '3lod') {
        this.activeTab.set('lod');
      }
      // Auto-open plan toggle when a plan arrives
      if (phase === 'executing' && this.state.dag().length > 0) {
        this.planOpen.set(false);  // reset on new run
      }
    });
  }

  private readonly baseTabs: { id: Tab; label: string }[] = [
    { id: 'answer',    label: 'Answer' },
    { id: 'plan',      label: 'Plan' },
    { id: 'citations', label: 'Citations' },
    { id: 'audit',     label: 'Audit' },
    { id: 'trace',     label: 'Trace' },
    { id: 'dashboard', label: 'Dashboard' },
  ];

  readonly visibleTabs = computed<{ id: Tab; label: string }[]>(() => {
    const tabs = [...this.baseTabs];
    tabs.push({ id: 'lod', label: '3LoD' });
    tabs.push({ id: 'benchmark', label: 'Bench' });
    return tabs;
  });

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
          confidence: (ev.payload['confidence'] as number) ?? 0,
        });
      }
    }
    return scores;
  });

  readonly canBenchmark = computed(() => {
    const q = this.state.activeQuestion();
    return q.length > 0 && this.state.phase() !== 'planning' && this.state.phase() !== 'executing';
  });

  verOk(v: unknown): boolean {
    return typeof v === 'object' && v !== null && (v as any)['ok'] === true;
  }
  verTotal(v: unknown): number {
    return typeof v === 'object' && v !== null ? ((v as any)['total'] ?? 0) : 0;
  }

  asArr(v: unknown): any[] { return Array.isArray(v) ? v : []; }
  asString(v: unknown): string { return typeof v === 'string' ? v : ''; }
  planSteps(plan: unknown): any[] { return this.asArr((plan as any)?.['steps']); }
  planSource(plan: unknown): string { return String((plan as any)?.['source'] ?? ''); }

  fmtAnswer(v: unknown): string {
    if (typeof v === 'string') return v;
    if (v == null) return '';
    return JSON.stringify(v, null, 2);
  }

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
    return this.waterfallSteps(answer).length === 0;
  }

  slugVerdict(verdict: unknown): string {
    return String(verdict ?? '').toLowerCase().replace(/\s+/g, '-').replace(/[^a-z-]/g, '');
  }

  primTypeOf(name: string): string { return (name as string)?.split('.')[0] ?? ''; }
  primTypeLabel(name: string): string { return this.primTypeOf(name).slice(0, 3).toUpperCase(); }
  truncate(s: string, n: number): string { return s && s.length > n ? s.slice(0, n) + '…' : (s ?? ''); }

  confBarClass(c: number): string {
    if (c >= 0.8) return 'conf-high';
    if (c >= 0.5) return 'conf-mid';
    return 'conf-low';
  }

  citeLocClass(loc: string): string {
    return loc.startsWith('row=') ? 'tape' : '';
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
      case 'plan_ready':      return `${p['step_count']} steps · ${p['source']}`;
      case 'step_started':    return p['primitive'] ?? '';
      case 'step_finished':   return `${p['primitive']} · conf ${(p['confidence'] ?? 0).toFixed(2)} · ${p['citations']?.length ?? 0} cites`;
      case 'human_review_req': return `${p['primitive']} · conf ${(p['confidence'] ?? 0).toFixed(2)} < ${p['floor']}`;
      case 'run_finished':    return `${p['step_count']} steps complete`;
      case 'run_error':       return p['message'] ?? 'error';
      default: return '';
    }
  }

  readonly expandedStep = signal<string | null>(null);
  toggleStep(stepId: string): void { this.expandedStep.update(cur => cur === stepId ? null : stepId); }

  loadTrace(attempt = 0): void {
    const id = this.state.runId();
    if (!id) return;
    if (attempt === 0) { this.traceData.set(null); this.traceLoading.set(true); }
    this.api.getTrace(id).subscribe({
      next: (data) => { this.traceData.set(data); this.traceLoading.set(false); },
      error: (err) => {
        if ((err?.status === 404 || err?.status === 0) && attempt < 15) {
          setTimeout(() => this.loadTrace(attempt + 1), 1500);
        } else {
          this.traceLoading.set(false);
        }
      },
    });
  }

  selectTab(tab: Tab): void {
    this.activeTab.set(tab);
    if (tab !== 'dashboard') this.expanded.set(false);
    if (tab === 'trace') {
      const phase = this.state.phase();
      if ((phase === 'done' || phase === 'verifying') && !this.traceData() && !this.traceLoading()) {
        this.loadTrace();
      }
    }
  }

  toggleExpand(): void { this.expanded.update(v => !v); }

  openAuditDrawer(): void {
    this.auditDrawer?.open();
  }

  runBenchmark(): void {
    const q = this.state.activeQuestion();
    if (!q) return;
    this.api.benchmark(q, ['thorough', 'minimal', 'parallel_first']).subscribe({
      next: (resp) => {
        this.benchmarkRuns.set(resp.runs);
        this.activeTab.set('benchmark');
      },
    });
  }

  confClass(c: unknown): string {
    const n = typeof c === 'number' ? c : 0;
    if (n >= 0.8) return 'conf-val conf-high';
    if (n >= 0.5) return 'conf-val conf-mid';
    return 'conf-val conf-low';
  }

  resultVisualizations(result: Record<string, unknown>): any[] {
    if (Array.isArray(result['visualizations'])) return result['visualizations'];
    const answer = result['answer'];
    if (typeof answer === 'object' && answer !== null) {
      const a = answer as Record<string, unknown>;
      if (Array.isArray(a['visualizations'])) return a['visualizations'];
      const dash = a['dashboard'] as Record<string, unknown> | undefined;
      if (dash) {
        const vizs: any[] = [];
        if (Array.isArray(dash['cards'])) vizs.push(...dash['cards']);
        if (Array.isArray(dash['tables'])) vizs.push(...dash['tables']);
        return vizs;
      }
    }
    return [];
  }

  fmtMs(ms: unknown): string {
    const n = typeof ms === 'number' ? ms : 0;
    return n < 1000 ? `${n.toFixed(0)}ms` : `${(n / 1000).toFixed(1)}s`;
  }

  fmtJson(v: unknown): string {
    try { return JSON.stringify(v, null, 2); }
    catch { return String(v); }
  }
}
