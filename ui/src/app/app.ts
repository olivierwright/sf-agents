import { Component, inject, OnInit, ChangeDetectionStrategy, ViewChild } from '@angular/core';
import { RunStateService } from './services/run-state.service';
import { TopbarComponent } from './components/topbar.component';
import { DealSidebarComponent } from './components/deal-sidebar.component';
import { ExecutionTerminalComponent } from './components/execution-terminal.component';
import { ResultsPanelComponent } from './components/results-panel.component';
import { DealContextBarComponent } from './components/deal-context-bar.component';
import { AuditDrawerComponent } from './components/audit-drawer.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    TopbarComponent,
    DealContextBarComponent,
    DealSidebarComponent,
    ExecutionTerminalComponent,
    ResultsPanelComponent,
    AuditDrawerComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="terminal-shell">
      <app-topbar />
      <app-deal-context-bar />
      <div class="terminal-body">
        <app-deal-sidebar />
        <app-execution-terminal />
        <app-results-panel />
      </div>
    </div>
    <!-- Audit drawer lives outside the main layout so it slides over everything -->
    <app-audit-drawer #auditDrawer />
  `,
  styles: [
    `
      :host {
        display: block;
      }
      .terminal-shell {
        display: flex;
        flex-direction: column;
        height: 100vh;
        overflow: hidden;
      }
      .terminal-body {
        display: flex;
        flex: 1;
        min-height: 0; /* lets flex children shrink below content size */
        overflow: hidden;
      }
      /* Custom elements are inline by default — make them block + fill height */
      app-deal-sidebar {
        display: block;
        flex-shrink: 0;
        height: 100%;
        overflow: hidden;
      }
      app-execution-terminal {
        display: flex;
        flex: 1;
        min-width: 0;
        height: 100%;
        overflow: hidden;
      }
      app-results-panel {
        display: block;
        flex-shrink: 0;
        height: 100%;
        overflow: hidden;
      }
    `,
  ],
})
export class App implements OnInit {
  private state = inject(RunStateService);
  @ViewChild('auditDrawer') auditDrawer!: AuditDrawerComponent;

  ngOnInit(): void {
    this.state.loadInitialData();
  }
}
