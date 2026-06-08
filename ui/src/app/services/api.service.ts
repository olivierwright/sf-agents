import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

// ── Interfaces ────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  model: string;
  region: string;
  deal_loaded: boolean;
}

export interface ClarificationOption {
  label: string;
  value: string;
  recommended: boolean;
}

export interface RecipeInfo {
  id: string;
  label: string;
  description: string;
  terms: string[];
  needs_clarification: boolean;
  clarification_options: ClarificationOption[] | null;
}

export interface UseCaseInfo {
  id: string;
  label: string;
  category: string;
  example_question: string;
  suggested_primitives: string[];
  description: string;
  terms: string[];
}

export interface PrimitiveInfo {
  name: string;
  version: string;
  capability: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
}

export interface StrategyInfo {
  id: string;
  label: string;
  description: string;
}

export interface DealDocument {
  name: string;
  type: string;
  pages: number;
}

export interface DealResponse {
  deal: { name: string; reporting_date: string | null; currency: string };
  portfolio: {
    loan_count: number;
    total_balance_eur: number | null;
    avg_interest_rate_pct: number | null;
  };
  green: {
    epc_breakdown: Record<string, number>;
    green_label_pct: number | null;
    construction_deposit_pct: number | null;
  };
  performance: {
    performing_status: Record<string, number>;
    arrears_buckets: Record<string, number>;
  };
  vintage: Record<string, number>;
  documents: DealDocument[];
  tape: { key_green_fields: string[] };
}

export interface RunStartResponse {
  run_id: string;
  stream_url: string;
  result_url: string;
}

export interface RunStatus {
  run_id: string;
  recipe: string;
  question: string;
  strategy: string;
  status: 'pending' | 'running' | 'done' | 'error';
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface BenchmarkRun {
  strategy: string;
  run_id: string;
  stream_url: string;
  result_url: string;
}

export interface BenchmarkResponse {
  question: string;
  runs: BenchmarkRun[];
}

export interface PeriodMetric {
  values: number[];
  changes_pct: (number | null)[];
}

export interface PeriodHighlight {
  metric: string;
  period: string;
  direction: 'increase' | 'decrease';
  magnitude_pct: number;
  from_value: number;
  to_value: number;
}

export interface PeriodComparisonResponse {
  periods: string[];
  files: string[];
  metrics: Record<string, PeriodMetric>;
  highlights: PeriodHighlight[];
  chart_data: {
    bar: { labels: string[]; datasets: { label: string; data: number[] }[] };
    line: { labels: string[]; datasets: { label: string; data: number[] }[] };
    distributions: Record<string, Record<string, Record<string, number>>>;
  };
  distributions: Record<string, Record<string, Record<string, number>>>;
}

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);

  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>('/api/health');
  }

  recipes(): Observable<RecipeInfo[]> {
    return this.http.get<RecipeInfo[]>('/api/recipes');
  }

  useCases(): Observable<UseCaseInfo[]> {
    return this.http.get<UseCaseInfo[]>('/api/use-cases');
  }

  primitives(): Observable<PrimitiveInfo[]> {
    return this.http.get<PrimitiveInfo[]>('/api/primitives');
  }

  strategies(): Observable<StrategyInfo[]> {
    return this.http.get<StrategyInfo[]>('/api/strategies');
  }

  deal(): Observable<DealResponse> {
    return this.http.get<DealResponse>('/api/deal');
  }

  startRun(recipe: string, question?: string, runId?: string): Observable<RunStartResponse> {
    return this.http.post<RunStartResponse>('/api/runs', {
      recipe,
      question: question ?? null,
      run_id: runId ?? null,
    });
  }

  startQuestion(
    question: string,
    strategy: string,
    documents?: Record<string, string>,
  ): Observable<RunStartResponse> {
    return this.http.post<RunStartResponse>('/api/runs', {
      question,
      strategy,
      documents: documents ?? null,
    });
  }

  benchmark(
    question: string,
    strategies: string[],
    documents?: Record<string, string>,
  ): Observable<BenchmarkResponse> {
    return this.http.post<BenchmarkResponse>('/api/benchmark', {
      question,
      strategies,
      documents: documents ?? null,
    });
  }

  getResult(runId: string): Observable<RunStatus> {
    return this.http.get<RunStatus>(`/api/runs/${runId}/result`);
  }

  clarify(runId: string, answer: string): Observable<{ status: string; run_id: string }> {
    return this.http.post<{ status: string; run_id: string }>(`/api/runs/${runId}/clarify`, {
      answer,
    });
  }

  getAudit(runId: string): Observable<Record<string, unknown>[]> {
    return this.http.get<Record<string, unknown>[]>(`/api/runs/${runId}/audit`);
  }

  getTrace(runId: string): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(`/api/runs/${runId}/trace`);
  }

  listRuns(): Observable<RunStatus[]> {
    return this.http.get<RunStatus[]>('/api/runs');
  }

  dealPeriods(): Observable<PeriodComparisonResponse> {
    return this.http.get<PeriodComparisonResponse>('/api/deal/periods');
  }
}
