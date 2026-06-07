import {
  Component,
  inject,
  signal,
  computed,
  ChangeDetectionStrategy,
  OnInit,
  OnDestroy,
  ElementRef,
  ViewChild,
  AfterViewInit,
  effect,
} from '@angular/core';
import { ApiService, PeriodComparisonResponse } from '../services/api.service';
import { Chart, registerables } from 'chart.js';

Chart.register(...registerables);

type DashTab = 'overview' | 'charts' | 'table';

@Component({
  selector: 'app-dashboard-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="dashboard">
      <div class="dash-header">
        <h3 class="dash-title">Portfolio Dashboard</h3>
        <div class="dash-tabs">
          @for (tab of dashTabs; track tab.id) {
            <button
              class="dash-tab"
              [class.active]="activeTab() === tab.id"
              (click)="activeTab.set(tab.id)"
            >{{ tab.label }}</button>
          }
        </div>
      </div>

      @if (loading()) {
        <div class="dash-loading">
          <div class="dash-spinner"></div>
          <span>Loading period data…</span>
        </div>
      } @else if (error()) {
        <div class="dash-error">{{ error() }}</div>
      } @else if (data()) {

        <!-- OVERVIEW TAB -->
        @if (activeTab() === 'overview') {
          <div class="kpi-grid">
            @for (card of kpiCards(); track card.metric) {
              <div class="kpi-card">
                <div class="kpi-label">{{ card.label }}</div>
                <div class="kpi-value">{{ card.formatted }}</div>
                @if (card.change !== null && card.change !== undefined) {
                  <div class="kpi-change" [class.up]="card.change > 0" [class.down]="card.change < 0">
                    <span class="kpi-arrow">{{ card.change > 0 ? '▲' : card.change < 0 ? '▼' : '—' }}</span>
                    {{ formatChange(card.change) }}
                  </div>
                }
              </div>
            }
          </div>

          @if (highlights().length > 0) {
            <div class="highlights-section">
              <div class="section-label">MATERIAL MOVEMENTS</div>
              @for (h of highlights(); track h.metric + h.period) {
                <div class="highlight-row" [class.up]="h.direction === 'increase'" [class.down]="h.direction === 'decrease'">
                  <span class="hl-arrow">{{ h.direction === 'increase' ? '▲' : '▼' }}</span>
                  <span class="hl-metric">{{ formatMetricName(h.metric) }}</span>
                  <span class="hl-mag">{{ h.magnitude_pct.toFixed(1) }}%</span>
                  <span class="hl-period">{{ h.period }}</span>
                </div>
              }
            </div>
          }
        }

        <!-- CHARTS TAB -->
        @if (activeTab() === 'charts') {
          <div class="charts-grid">
            <div class="chart-card">
              <div class="chart-title">Portfolio Balance</div>
              <canvas #balanceChart></canvas>
            </div>
            <div class="chart-card">
              <div class="chart-title">Rate & Performance Trends</div>
              <canvas #trendChart></canvas>
            </div>
            <div class="chart-card">
              <div class="chart-title">EPC Distribution (Latest)</div>
              <canvas #epcChart></canvas>
            </div>
            <div class="chart-card">
              <div class="chart-title">Loan Count</div>
              <canvas #countChart></canvas>
            </div>
          </div>
        }

        <!-- TABLE TAB -->
        @if (activeTab() === 'table') {
          <div class="table-section">
            <div class="section-label">PERIOD-OVER-PERIOD METRICS</div>
            <div class="table-wrap">
              <table class="metrics-table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    @for (p of data()!.periods; track p) {
                      <th>{{ p }}</th>
                      @if (!$first) {
                        <th class="change-col">Δ%</th>
                      }
                    }
                  </tr>
                </thead>
                <tbody>
                  @for (row of tableRows(); track row.metric) {
                    <tr>
                      <td class="metric-name">{{ row.label }}</td>
                      @for (cell of row.cells; track $index) {
                        <td class="metric-val">{{ cell.formatted }}</td>
                        @if (cell.change !== null && cell.change !== undefined) {
                          <td class="change-cell" [class.up]="cell.change > 0" [class.down]="cell.change < 0">
                            {{ formatChange(cell.change) }}
                          </td>
                        }
                      }
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </div>

          <!-- Distribution tables -->
          @for (dist of distributionTables(); track dist.column) {
            <div class="table-section">
              <div class="section-label">{{ dist.label }}</div>
              <div class="table-wrap">
                <table class="metrics-table">
                  <thead>
                    <tr>
                      <th>{{ dist.column }}</th>
                      @for (p of data()!.periods; track p) {
                        <th>{{ p }}</th>
                      }
                    </tr>
                  </thead>
                  <tbody>
                    @for (row of dist.rows; track row.bucket) {
                      <tr>
                        <td class="metric-name">{{ row.bucket }}</td>
                        @for (val of row.values; track $index) {
                          <td class="metric-val">{{ val }}</td>
                        }
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            </div>
          }
        }
      }
    </div>
  `,
  styles: [`
    .dashboard {
      padding: var(--sp-4);
      overflow-y: auto;
      height: 100%;
      container-type: inline-size;
    }
    .dash-header {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: var(--sp-4);
    }
    .dash-title {
      font-family: var(--font-display); font-size: 1.1rem;
      color: var(--text-primary); margin: 0;
    }
    .dash-tabs { display: flex; gap: var(--sp-1); }
    .dash-tab {
      padding: var(--sp-1) var(--sp-3); border: 1px solid var(--border);
      border-radius: var(--radius-sm); background: none; cursor: pointer;
      font-size: 0.75rem; color: var(--text-muted);
      font-family: var(--font-sans); transition: all 0.15s;
    }
    .dash-tab.active {
      background: var(--accent); color: #fff; border-color: var(--accent);
    }
    .dash-tab:hover:not(.active) { border-color: var(--accent); color: var(--accent); }

    .dash-loading {
      display: flex; align-items: center; gap: var(--sp-3);
      padding: var(--sp-8); justify-content: center;
      color: var(--text-muted); font-size: 0.8125rem;
    }
    .dash-spinner {
      width: 18px; height: 18px; border: 2px solid var(--border);
      border-top-color: var(--accent); border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .dash-error {
      padding: var(--sp-4); background: rgba(198,40,40,0.06);
      border: 1px solid rgba(198,40,40,0.2); border-radius: var(--radius-md);
      color: var(--color-danger); font-size: 0.8125rem;
    }

    /* KPI cards */
    .kpi-grid {
      display: grid; grid-template-columns: repeat(3, 1fr);
      gap: var(--sp-3); margin-bottom: var(--sp-4);
    }
    @container (min-width: 700px) {
      .kpi-grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
    }
    .kpi-card {
      background: var(--bg-surface); border: 1px solid var(--border);
      border-radius: var(--radius-md); padding: var(--sp-3);
    }
    .kpi-label {
      font-size: 0.6875rem; color: var(--text-muted);
      text-transform: uppercase; letter-spacing: 0.5px;
      margin-bottom: var(--sp-1);
    }
    .kpi-value {
      font-family: var(--font-mono); font-size: 1.1rem;
      font-weight: 600; color: var(--text-primary);
    }
    .kpi-change {
      font-family: var(--font-mono); font-size: 0.75rem;
      margin-top: var(--sp-1); display: flex; align-items: center; gap: 2px;
    }
    .kpi-change.up { color: var(--color-success); }
    .kpi-change.down { color: var(--color-danger); }
    .kpi-arrow { font-size: 0.625rem; }

    /* Highlights */
    .highlights-section { margin-bottom: var(--sp-4); }
    .section-label {
      font-size: 0.6875rem; font-weight: 600; color: var(--text-muted);
      text-transform: uppercase; letter-spacing: 0.5px;
      margin-bottom: var(--sp-2); font-family: var(--font-mono);
    }
    .highlight-row {
      display: flex; align-items: center; gap: var(--sp-2);
      padding: var(--sp-2) var(--sp-3); border-radius: var(--radius-sm);
      font-size: 0.8125rem; margin-bottom: var(--sp-1);
    }
    .highlight-row.up { background: rgba(46,125,50,0.06); }
    .highlight-row.down { background: rgba(198,40,40,0.06); }
    .hl-arrow { font-size: 0.625rem; }
    .highlight-row.up .hl-arrow { color: var(--color-success); }
    .highlight-row.down .hl-arrow { color: var(--color-danger); }
    .hl-metric { font-weight: 500; flex: 1; }
    .hl-mag {
      font-family: var(--font-mono); font-weight: 600; font-size: 0.75rem;
    }
    .highlight-row.up .hl-mag { color: var(--color-success); }
    .highlight-row.down .hl-mag { color: var(--color-danger); }
    .hl-period {
      font-family: var(--font-mono); font-size: 0.6875rem;
      color: var(--text-muted);
    }

    /* Charts */
    .charts-grid {
      display: grid; grid-template-columns: 1fr 1fr;
      gap: var(--sp-3);
    }
    @container (min-width: 900px) {
      .charts-grid { grid-template-columns: repeat(2, 1fr); }
      canvas { max-height: 320px; }
    }
    @container (min-width: 1200px) {
      .charts-grid { grid-template-columns: repeat(2, 1fr); gap: var(--sp-4); }
      canvas { max-height: 400px; }
    }
    .chart-card {
      background: var(--bg-surface); border: 1px solid var(--border);
      border-radius: var(--radius-md); padding: var(--sp-3);
    }
    .chart-title {
      font-size: 0.75rem; font-weight: 600; color: var(--text-secondary);
      margin-bottom: var(--sp-2);
    }
    canvas { width: 100% !important; max-height: 200px; }

    @container (min-width: 700px) {
      .chart-card { padding: var(--sp-4); }
      .chart-title { font-size: 0.875rem; }
      .metrics-table { font-size: 0.8125rem; }
      .kpi-value { font-size: 1.3rem; }
    }

    /* Tables */
    .table-section { margin-bottom: var(--sp-4); }
    .table-wrap { overflow-x: auto; }
    .metrics-table {
      width: 100%; border-collapse: collapse; font-size: 0.75rem;
    }
    .metrics-table th {
      text-align: left; padding: var(--sp-2) var(--sp-3);
      border-bottom: 2px solid var(--border); font-weight: 600;
      color: var(--text-secondary); font-family: var(--font-mono);
      font-size: 0.6875rem; white-space: nowrap;
    }
    .metrics-table td {
      padding: var(--sp-2) var(--sp-3); border-bottom: 1px solid var(--border);
    }
    .metric-name { font-weight: 500; color: var(--text-primary); white-space: nowrap; }
    .metric-val { font-family: var(--font-mono); color: var(--text-secondary); text-align: right; }
    .change-col { font-size: 0.625rem; }
    .change-cell {
      font-family: var(--font-mono); font-size: 0.6875rem; text-align: right;
    }
    .change-cell.up { color: var(--color-success); }
    .change-cell.down { color: var(--color-danger); }
  `],
})
export class DashboardPanelComponent implements OnInit, OnDestroy {
  @ViewChild('balanceChart') balanceCanvas!: ElementRef<HTMLCanvasElement>;
  @ViewChild('trendChart') trendCanvas!: ElementRef<HTMLCanvasElement>;
  @ViewChild('epcChart') epcCanvas!: ElementRef<HTMLCanvasElement>;
  @ViewChild('countChart') countCanvas!: ElementRef<HTMLCanvasElement>;

  private api = inject(ApiService);
  private charts: Chart[] = [];

  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly data = signal<PeriodComparisonResponse | null>(null);
  readonly activeTab = signal<DashTab>('overview');

  readonly dashTabs: { id: DashTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'charts', label: 'Charts' },
    { id: 'table', label: 'Tables' },
  ];

  // Render charts when tab switches to 'charts'
  private chartEffect = effect(() => {
    const tab = this.activeTab();
    const d = this.data();
    if (tab === 'charts' && d) {
      // Defer to next microtask so canvas elements are in the DOM
      setTimeout(() => this.renderCharts(d), 0);
    }
  });

  readonly kpiCards = computed(() => {
    const d = this.data();
    if (!d) return [];
    const metrics = d.metrics;
    const cards: { metric: string; label: string; formatted: string; change: number | null }[] = [];

    const defs: { key: string; label: string; fmt: (v: number) => string }[] = [
      { key: 'loan_count', label: 'Loan Count', fmt: (v) => v.toLocaleString() },
      { key: 'total_balance', label: 'Total Balance', fmt: (v) => '€' + (v / 1e6).toFixed(1) + 'M' },
      { key: 'avg_balance', label: 'Avg Balance', fmt: (v) => '€' + (v / 1e3).toFixed(0) + 'K' },
      { key: 'avg_interest_rate_pct', label: 'Avg Rate', fmt: (v) => v.toFixed(2) + '%' },
      { key: 'performing_pct', label: 'Performing', fmt: (v) => v.toFixed(1) + '%' },
      { key: 'green_label_pct', label: 'Green Label', fmt: (v) => v.toFixed(1) + '%' },
      { key: 'arrears_pct', label: 'Arrears', fmt: (v) => v.toFixed(1) + '%' },
      { key: 'avg_ltv', label: 'Avg LTV', fmt: (v) => v.toFixed(1) + '%' },
      { key: 'weighted_avg_rate', label: 'WAC Rate', fmt: (v) => v.toFixed(2) + '%' },
    ];

    for (const def of defs) {
      const m = metrics[def.key];
      if (!m) continue;
      const latest = m.values[m.values.length - 1];
      const change = m.changes_pct[m.changes_pct.length - 1];
      cards.push({ metric: def.key, label: def.label, formatted: def.fmt(latest), change: change ?? null });
    }
    return cards;
  });

  readonly highlights = computed(() => this.data()?.highlights ?? []);

  readonly tableRows = computed(() => {
    const d = this.data();
    if (!d) return [];
    const labels: Record<string, string> = {
      loan_count: 'Loan Count',
      total_balance: 'Total Balance (EUR)',
      avg_balance: 'Avg Balance (EUR)',
      avg_interest_rate_pct: 'Avg Interest Rate (%)',
      weighted_avg_rate: 'WAC Rate (%)',
      performing_pct: 'Performing (%)',
      arrears_pct: 'Arrears (%)',
      green_label_pct: 'Green Label (%)',
      avg_ltv: 'Avg LTV (%)',
    };
    const rows: { metric: string; label: string; cells: { formatted: string; change: number | null | undefined }[] }[] = [];
    for (const [key, m] of Object.entries(d.metrics)) {
      const cells = m.values.map((v, i) => ({
        formatted: typeof v === 'number' ? (v > 10000 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : v.toFixed(2)) : String(v),
        change: i === 0 ? undefined : (m.changes_pct[i] ?? null),
      }));
      // Only include first cell without change column
      const adjustedCells: typeof cells = [];
      for (let i = 0; i < cells.length; i++) {
        if (i === 0) {
          adjustedCells.push({ formatted: cells[i].formatted, change: undefined });
        } else {
          adjustedCells.push(cells[i]);
        }
      }
      rows.push({ metric: key, label: labels[key] ?? key, cells: adjustedCells });
    }
    return rows;
  });

  readonly distributionTables = computed(() => {
    const d = this.data();
    if (!d || !d.distributions) return [];
    const tables: { column: string; label: string; rows: { bucket: string; values: number[] }[] }[] = [];
    const labelMap: Record<string, string> = {
      epc_label: 'EPC DISTRIBUTION',
      arrears_bucket: 'ARREARS DISTRIBUTION',
      rate_type: 'RATE TYPE DISTRIBUTION',
    };
    for (const [period, dists] of Object.entries(d.distributions)) {
      // We process distributions differently — group by column across periods
      for (const col of Object.keys(dists)) {
        if (!tables.find(t => t.column === col)) {
          tables.push({ column: col, label: labelMap[col] ?? col.toUpperCase(), rows: [] });
        }
      }
    }
    // Fill in values
    for (const table of tables) {
      const allBuckets = new Set<string>();
      for (const period of d.periods) {
        const dist = d.distributions[period]?.[table.column] ?? {};
        for (const bucket of Object.keys(dist)) allBuckets.add(bucket);
      }
      const sortedBuckets = [...allBuckets].sort();
      table.rows = sortedBuckets.map(bucket => ({
        bucket,
        values: d.periods.map(p => d.distributions[p]?.[table.column]?.[bucket] ?? 0),
      }));
    }
    return tables;
  });

  ngOnInit(): void {
    this.api.dealPeriods().subscribe({
      next: (resp) => {
        this.data.set(resp);
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(err?.error?.detail ?? 'Failed to load period data');
        this.loading.set(false);
      },
    });
  }

  ngOnDestroy(): void {
    this.destroyCharts();
  }

  formatChange(change: number | null | undefined): string {
    if (change === null || change === undefined) return '';
    const sign = change > 0 ? '+' : '';
    return `${sign}${change.toFixed(1)}%`;
  }

  formatMetricName(name: string): string {
    return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  private destroyCharts(): void {
    for (const c of this.charts) c.destroy();
    this.charts = [];
  }

  private renderCharts(d: PeriodComparisonResponse): void {
    this.destroyCharts();
    const baseColors = ['#1B6F6B', '#2A9D97', '#2D5A8E', '#7B5EA7', '#E65100', '#C62828'];

    // Balance bar chart
    if (this.balanceCanvas?.nativeElement) {
      this.charts.push(new Chart(this.balanceCanvas.nativeElement, {
        type: 'bar',
        data: {
          labels: d.chart_data.bar.labels,
          datasets: [{
            label: 'Total Balance (EUR)',
            data: d.chart_data.bar.datasets[0]?.data ?? [],
            backgroundColor: '#1B6F6B',
            borderRadius: 4,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            y: { ticks: { callback: (v) => '€' + (Number(v) / 1e6).toFixed(0) + 'M' } },
          },
        },
      }));
    }

    // Trend line chart
    if (this.trendCanvas?.nativeElement) {
      const datasets = d.chart_data.line.datasets.map((ds, i) => ({
        label: ds.label,
        data: ds.data,
        borderColor: baseColors[i % baseColors.length],
        backgroundColor: 'transparent',
        tension: 0.3,
        pointRadius: 4,
        borderWidth: 2,
      }));
      this.charts.push(new Chart(this.trendCanvas.nativeElement, {
        type: 'line',
        data: { labels: d.chart_data.line.labels, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } },
        },
      }));
    }

    // EPC pie chart (latest period)
    if (this.epcCanvas?.nativeElement) {
      const latestPeriod = d.periods[d.periods.length - 1];
      const epcDist = d.distributions[latestPeriod]?.['epc_label'] ?? {};
      const labels = Object.keys(epcDist);
      const values = Object.values(epcDist);
      if (labels.length > 0) {
        const colors = labels.map((_, i) => baseColors[i % baseColors.length]);
        this.charts.push(new Chart(this.epcCanvas.nativeElement, {
          type: 'doughnut',
          data: {
            labels,
            datasets: [{ data: values, backgroundColor: colors, borderWidth: 1 }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: 'bottom', labels: { font: { size: 10 } } } },
          },
        }));
      }
    }

    // Loan count bar chart
    if (this.countCanvas?.nativeElement) {
      this.charts.push(new Chart(this.countCanvas.nativeElement, {
        type: 'bar',
        data: {
          labels: d.chart_data.bar.labels,
          datasets: [{
            label: 'Loan Count',
            data: d.chart_data.bar.datasets[1]?.data ?? [],
            backgroundColor: '#2D5A8E',
            borderRadius: 4,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
        },
      }));
    }
  }
}
