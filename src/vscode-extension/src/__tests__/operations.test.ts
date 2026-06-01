import { describe, it, expect, vi, beforeEach } from 'vitest';
import { runErc, runDrc, fixErc, suggestImprovements } from '../operations';

describe('Operations', () => {
  const mockClient = {
    callTool: vi.fn(),
    listTools: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('runErc', () => {
    it('should call validate_schematic with file path', async () => {
      mockClient.callTool.mockResolvedValue({
        content: [{ type: 'text', text: '{"violations": [], "pass": true}' }],
      });
      const result = await runErc(mockClient as any, '/path/to/test.kicad_sch');
      expect(mockClient.callTool).toHaveBeenCalledWith('validate_schematic', { path: '/path/to/test.kicad_sch' });
      expect(result.pass).toBe(true);
    });

    it('should handle ERC failures', async () => {
      mockClient.callTool.mockResolvedValue({
        content: [{ type: 'text', text: '{"violations": [{"type": "pin_to_pin"}], "pass": false}' }],
        isError: false,
      });
      const result = await runErc(mockClient as any, '/path/to/test.kicad_sch');
      expect(result.pass).toBe(false);
      expect(result.violations).toHaveLength(1);
    });
  });

  describe('runDrc', () => {
    it('should call validate_pcb with file path', async () => {
      mockClient.callTool.mockResolvedValue({
        content: [{ type: 'text', text: '{"violations": [], "pass": true}' }],
      });
      const result = await runDrc(mockClient as any, '/path/to/test.kicad_pcb');
      expect(mockClient.callTool).toHaveBeenCalledWith('validate_pcb', { path: '/path/to/test.kicad_pcb' });
      expect(result.pass).toBe(true);
    });
  });

  describe('fixErc', () => {
    it('should call erc_auto_fix with file path', async () => {
      mockClient.callTool.mockResolvedValue({
        content: [{ type: 'text', text: '{"fixed": 5, "remaining": 0}' }],
      });
      const result = await fixErc(mockClient as any, '/path/to/test.kicad_sch');
      expect(mockClient.callTool).toHaveBeenCalledWith('erc_auto_fix', { path: '/path/to/test.kicad_sch' });
      expect(result.fixed).toBe(5);
    });
  });

  describe('suggestImprovements', () => {
    it('should call design_review with file path', async () => {
      mockClient.callTool.mockResolvedValue({
        content: [{ type: 'text', text: '{"suggestions": ["Add decoupling caps"]}' }],
      });
      const result = await suggestImprovements(mockClient as any, '/path/to/test.kicad_sch');
      expect(mockClient.callTool).toHaveBeenCalledWith('design_review', { path: '/path/to/test.kicad_sch' });
      expect(result.suggestions).toHaveLength(1);
    });
  });
});
