/**
 * ERC report provider for sidebar panel.
 *
 * Parses ERC results into categorized tree items for the sidebar.
 */

export interface ErcViolationItem {
  severity: 'error' | 'warning' | 'info';
  type: string;
  description: string;
  position?: { x: number; y: number };
}

export class ErcReportProvider {
  private violations: ErcViolationItem[] = [];
  private passStatus: boolean = false;

  updateFromReport(report: {
    pass: boolean;
    violations: Array<{
      type: string;
      severity: string;
      description: string;
      position?: { x: number; y: number };
    }>;
  }): void {
    this.passStatus = report.pass;
    this.violations = report.violations.map(v => ({
      severity: (v.severity as 'error' | 'warning' | 'info') ?? 'warning',
      type: v.type,
      description: v.description,
      position: v.position,
    }));
  }

  getViolations(): ErcViolationItem[] {
    return [...this.violations];
  }

  getErrors(): ErcViolationItem[] {
    return this.violations.filter(v => v.severity === 'error');
  }

  getWarnings(): ErcViolationItem[] {
    return this.violations.filter(v => v.severity === 'warning');
  }

  get pass(): boolean {
    return this.passStatus;
  }

  get count(): number {
    return this.violations.length;
  }

  clear(): void {
    this.violations = [];
    this.passStatus = false;
  }
}
