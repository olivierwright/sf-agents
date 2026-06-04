import { Component, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RunStateService, DagStep } from '../services/run-state.service';
import { ApiService, PrimitiveInfo, UseCaseInfo } from '../services/api.service';

@Component({
  selector: 'app-deal-sidebar',
  standalone: true,
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <aside class="sidebar">
      <!-- ── Deal Metrics ──────────────────────────── -->
      <div class="section">
        <button class="section-toggle" (click)="metricsOpen.update((v) => !v)">
          <span class="toggle-arrow">{{ metricsOpen() ? '▾' : '▸' }}</span>
          <span class="section-label">DEAL METRICS</span>
        </button>
        @if (metricsOpen() && state.deal(); as d) {
          <div class="section-body">
            <!-- Portfolio row -->
            <div class="metric-grid">
              <div class="metric-cell">
                <span class="mc-val mono">{{ d.portfolio.loan_count | number }}</span>
                <span class="mc-lbl">Loans</span>
              </div>
              <div class="metric-cell">
                <span class="mc-val mono">€{{ fmtBal(d.portfolio.total_balance_eur) }}</span>
                <span class="mc-lbl">Portfolio</span>
              </div>
              <div class="metric-cell">
                <span class="mc-val mono">{{ d.portfolio.avg_interest_rate_pct }}%</span>
                <span class="mc-lbl">Avg Rate</span>
              </div>
            </div>

            <!-- Performance bar -->
            <div class="perf-section">
              <div class="perf-label-row">
                <span class="perf-label">Performance</span>
                <span class="mono perf-pct" style="color: var(--color-success)"
                  >{{ perfPct(d) }}% performing</span
                >
              </div>
              <div class="perf-bar">
                <div class="perf-fill-good" [style.width.%]="perfPct(d)"></div>
                <div class="perf-fill-bad" [style.width.%]="100 - perfPct(d)"></div>
              </div>
            </div>

            <!-- Green EPC heatmap -->
            <div class="epc-section">
              <span class="perf-label">EPC Distribution</span>
              <div class="epc-bar">
                @for (entry of epcEntries(d); track entry.label) {
                  <div
                    class="epc-seg"
                    [style.flex]="entry.count"
                    [style.background]="epcColor(entry.label)"
                    [title]="entry.label + ': ' + entry.count + ' loans'"
                  ></div>
                }
              </div>
              <div class="epc-legend">
                @for (entry of epcEntries(d); track entry.label) {
                  <span class="epc-lbl">
                    <span class="epc-dot" [style.background]="epcColor(entry.label)"></span>
                    {{ entry.label }}
                  </span>
                }
              </div>
            </div>

            <!-- Documents -->
            <div class="docs-section">
              <span class="perf-label">Documents</span>
              @for (doc of d.documents; track doc.name) {
                <div class="doc-row">
                  <span class="doc-icon">{{ docIcon(doc.type) }}</span>
                  <span class="doc-name">{{ doc.name }}</span>
                  <span class="doc-pages mono">{{ doc.pages }}p</span>
                </div>
              }
            </div>
          </div>
        }
      </div>

      <!-- ── Use Cases ─────────────────────────────── -->
      <div class="section">
        <button class="section-toggle" (click)="casesOpen.update((v) => !v)">
          <span class="toggle-arrow">{{ casesOpen() ? '▾' : '▸' }}</span>
          <span class="section-label">ANALYSIS TEMPLATES</span>
        </button>
        @if (casesOpen()) {
          <div class="section-body use-cases-list">
            @for (uc of state.useCases(); track uc.id) {
              <button
                class="uc-row"
                [class.active]="state.questionDraft() === uc.example_question"
                [disabled]="state.isRunning()"
                (click)="selectUseCase(uc)"
              >
                <span class="uc-icon">{{ catIcon(uc.category) }}</span>
                <span class="uc-text">
                  <span class="uc-label">{{ uc.label }}</span>
                  <span class="uc-q">{{ uc.example_question }}</span>
                </span>
              </button>
            }
          </div>
        }
      </div>

      <!-- ── Primitives Registry ───────────────────── -->
      <div class="section">
        <button class="section-toggle" (click)="primsOpen.update((v) => !v)">
          <span class="toggle-arrow">{{ primsOpen() ? '▾' : '▸' }}</span>
          <span class="section-label">PRIMITIVE REGISTRY</span>
          @if (primitives().length > 0) {
            <span class="count-badge mono">{{ primitives().length }}</span>
          }
        </button>
        @if (primsOpen()) {
          <div class="section-body">
            @for (p of primitives(); track p.name) {
              <div class="prim-row">
                <span class="prim-type-badge" [class]="'ptype-' + primType(p.name)">{{
                  primType(p.name).slice(0, 3).toUpperCase()
                }}</span>
                <span class="prim-name mono">{{ p.name }}</span>
              </div>
            }
          </div>
        }
      </div>
    </aside>
  `,
  styles: [
    `
      .sidebar {
        width: 260px;
        min-width: 260px;
        height: 100%;
        border-right: 1px solid var(--border);
        background: var(--bg-surface);
        overflow-y: auto;
        display: flex;
        flex-direction: column;
      }
      .section {
        border-bottom: 1px solid var(--border);
      }
      .section-toggle {
        display: flex;
        align-items: center;
        gap: var(--sp-2);
        width: 100%;
        padding: var(--sp-3) var(--sp-4);
        background: none;
        border: none;
        cursor: pointer;
        text-align: left;
        transition: background var(--duration-fast);
      }
      .section-toggle:hover {
        background: var(--bg-canvas);
      }
      .toggle-arrow {
        font-size: 0.625rem;
        color: var(--text-muted);
      }
      .section-label {
        font-size: 0.625rem;
        font-weight: 600;
        letter-spacing: 0.1em;
        color: var(--text-muted);
        text-transform: uppercase;
      }
      .count-badge {
        margin-left: auto;
        font-size: 0.5625rem;
        background: var(--bg-canvas);
        border: 1px solid var(--border);
        border-radius: var(--radius-full);
        padding: 1px var(--sp-2);
        color: var(--text-muted);
      }
      .section-body {
        padding: var(--sp-2) var(--sp-4) var(--sp-4);
      }

      /* Metrics */
      .metric-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: var(--sp-2);
        margin-bottom: var(--sp-4);
      }
      .metric-cell {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 1px;
      }
      .mc-val {
        font-size: 0.875rem;
        font-weight: 600;
      }
      .mc-lbl {
        font-size: 0.5625rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--text-muted);
      }

      /* Performance bar */
      .perf-section {
        margin-bottom: var(--sp-4);
      }
      .perf-label-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: var(--sp-1);
      }
      .perf-label {
        font-size: 0.625rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-muted);
        font-weight: 600;
      }
      .perf-pct {
        font-size: 0.6875rem;
      }
      .perf-bar {
        display: flex;
        height: 6px;
        border-radius: 3px;
        overflow: hidden;
        background: var(--border);
      }
      .perf-fill-good {
        background: var(--color-success);
        transition: width var(--duration-slow);
      }
      .perf-fill-bad {
        background: var(--color-danger);
        opacity: 0.5;
      }

      /* EPC */
      .epc-section {
        margin-bottom: var(--sp-4);
      }
      .epc-bar {
        display: flex;
        height: 8px;
        border-radius: 4px;
        overflow: hidden;
        margin: var(--sp-2) 0 var(--sp-1);
        gap: 1px;
      }
      .epc-seg {
        min-width: 2px;
        transition: flex var(--duration-slow);
      }
      .epc-legend {
        display: flex;
        gap: var(--sp-2);
        flex-wrap: wrap;
      }
      .epc-lbl {
        display: flex;
        align-items: center;
        gap: 3px;
        font-size: 0.5625rem;
        color: var(--text-muted);
      }
      .epc-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        flex-shrink: 0;
      }

      /* Documents */
      .docs-section {
        margin-top: var(--sp-2);
      }
      .doc-row {
        display: flex;
        align-items: center;
        gap: var(--sp-2);
        padding: var(--sp-1) 0;
        font-size: 0.6875rem;
      }
      .doc-icon {
        font-size: 0.75rem;
      }
      .doc-name {
        color: var(--text-secondary);
        flex: 1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      .doc-pages {
        color: var(--text-muted);
        font-size: 0.5625rem;
        flex-shrink: 0;
      }

      /* Use cases */
      .use-cases-list {
        padding: var(--sp-2) 0;
      }
      .uc-row {
        display: flex;
        align-items: flex-start;
        gap: var(--sp-2);
        width: 100%;
        padding: var(--sp-2) var(--sp-4);
        background: none;
        border: none;
        cursor: pointer;
        text-align: left;
        transition: background var(--duration-fast);
        border-left: 2px solid transparent;
      }
      .uc-row:hover:not([disabled]) {
        background: var(--bg-canvas);
        border-left-color: var(--accent);
      }
      .uc-row.active {
        background: rgba(27, 111, 107, 0.06);
        border-left-color: var(--accent);
      }
      .uc-row[disabled] {
        opacity: 0.5;
        cursor: not-allowed;
      }
      .uc-icon {
        font-size: 0.875rem;
        flex-shrink: 0;
        padding-top: 1px;
      }
      .uc-text {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .uc-label {
        font-size: 0.75rem;
        font-weight: 600;
        color: var(--text-primary);
      }
      .uc-q {
        font-size: 0.625rem;
        color: var(--text-muted);
        line-height: 1.4;
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
      }

      /* Primitives */
      .prim-row {
        display: flex;
        align-items: center;
        gap: var(--sp-2);
        padding: var(--sp-1) 0;
      }
      .prim-type-badge {
        font-size: 0.5rem;
        font-family: var(--font-mono);
        font-weight: 600;
        padding: 1px 4px;
        border-radius: var(--radius-sm);
        flex-shrink: 0;
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
      .prim-name {
        font-size: 0.625rem;
        color: var(--text-secondary);
      }
    `,
  ],
})
export class DealSidebarComponent {
  protected state = inject(RunStateService);
  private api = inject(ApiService);

  readonly metricsOpen = signal(true);
  readonly casesOpen = signal(true);
  readonly primsOpen = signal(false);
  readonly primitives = signal<PrimitiveInfo[]>([]);

  ngOnInit(): void {
    this.api.primitives().subscribe((p) => this.primitives.set(p));
  }

  selectUseCase(uc: UseCaseInfo): void {
    this.state.questionDraft.set(uc.example_question);
    this.state.strategyDraft.set('thorough');
  }

  primType(name: string): string {
    return name.split('.')[0] ?? 'connector';
  }

  fmtBal(v: number | null): string {
    if (v == null) return '—';
    if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(0) + 'M';
    return v.toLocaleString();
  }

  perfPct(d: any): number {
    const perf = d.performance?.performing_status ?? {};
    const total = Object.values(perf).reduce((a: any, b: any) => a + b, 0) as number;
    return total > 0 ? Math.round(((perf['performing'] ?? 0) / total) * 100) : 0;
  }

  epcEntries(d: any): { label: string; count: number }[] {
    const epc = d.green?.epc_breakdown ?? {};
    return Object.entries(epc)
      .map(([label, count]) => ({ label, count: count as number }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }

  epcColor(label: string): string {
    const colors: Record<string, string> = {
      A: '#2E7D32',
      B: '#558B2F',
      C: '#F9A825',
      D: '#E65100',
      E: '#C62828',
      F: '#6A1A1A',
      G: '#4A0000',
    };
    return colors[label] ?? '#8C8C8C';
  }

  docIcon(type: string): string {
    const icons: Record<string, string> = {
      prospectus: '📋',
      investor_report: '📊',
      spo: '🌱',
      impact_report: '📈',
    };
    return icons[type] ?? '📄';
  }

  catIcon(cat: string): string {
    const icons: Record<string, string> = {
      documentation: '📋',
      esg: '🌱',
      performance: '📈',
      compliance: '⚖️',
      structure: '🏗️',
      ratings: '⭐',
    };
    return icons[cat] ?? '🔍';
  }
}
