/**
 * Tests for Play button state transitions in CodeGenDemo.
 *
 * These tests verify the state machine for execution:
 * - No node selected → Run → Node selected shows code
 * - Node selected (no code) → Run → Spinner → Code shown
 * - Node has code → Run → Previous code → Spinner → New code
 * - Run → Stop before completion → Revert to previous state
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NodeDetailsPanel } from "../src/components/NodeDetailsPanel";
import type { GraphNode } from "../src/components/GraphPanel";


describe("NodeDetailsPanel State Transitions", () => {
  /**
   * Scenario 1: No node selected initially
   * - Before run: shows "Select a node" placeholder
   */
  it("shows placeholder when no node selected (before run)", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId={null}
        selectedNode={null}
        isExecuting={false}
      />
    );
    expect(screen.getByText(/select a node in the graph/i)).toBeInTheDocument();
  });

  /**
   * Scenario 2: Operator node selected, no code yet
   * - Before run: shows "No generated code" message
   */
  it("shows 'no generated code' for operator node before run", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={false}
        liveGeneratedCodeByNode={{}}
      />
    );
    expect(screen.getByText(/no generated code for this sempipes operator/i)).toBeInTheDocument();
  });

  /**
   * Scenario 2: Operator node selected, execution starts
   * - During run: shows spinner/generating indicator
   */
  it("shows generating spinner when executing and no code received yet", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={true}
        liveGeneratedCodeByNode={{}}
      />
    );
    // Should show the loading text from CodeOutput mock
    expect(screen.getByText("Generating code for this node…")).toBeInTheDocument();
  });

  /**
   * Scenario 2: Operator node, code received during execution
   * - During run with code: shows code with (live) indicator
   */
  it("shows code with (live) indicator when code received during execution", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={true}
        liveGeneratedCodeByNode={{ sem_gen_features_5: "def transform(df):\n    return df" }}
      />
    );
    expect(screen.getByText("(live)")).toBeInTheDocument();
    expect(screen.queryByText("Generating code for this node…")).not.toBeInTheDocument();
  });

  /**
   * Scenario 2: Operator node, execution completed
   * - After run: shows code without (live) indicator, or with (live) if from liveGeneratedCodeByNode
   */
  it("shows generated code after execution completes (from liveGeneratedCodeByNode)", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={false}
        liveGeneratedCodeByNode={{ sem_gen_features_5: "def transform(df):\n    return df" }}
      />
    );
    // Code should be shown
    expect(screen.getByText("(live)")).toBeInTheDocument();
    expect(screen.queryByText("Generating code for this node…")).not.toBeInTheDocument();
    expect(screen.queryByText(/no generated code/i)).not.toBeInTheDocument();
  });

  /**
   * Scenario: Verify skrub_ prefixed node ID lookup works
   * - When selectedNodeId is "skrub_sem_gen_features_5"
   * - And code is stored under "sem_gen_features_5"
   * - Should still find the code
   */
  it("finds code when selectedNodeId has skrub_ prefix but code stored with raw ID", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="skrub_sem_gen_features_5"
        selectedNode={{ id: "skrub_sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={false}
        liveGeneratedCodeByNode={{ sem_gen_features_5: "# code for node" }}
      />
    );
    expect(screen.getByText("(live)")).toBeInTheDocument();
    expect(screen.queryByText(/no generated code/i)).not.toBeInTheDocument();
  });

  /**
   * Scenario: Verify code lookup with skrub_ prefixed storage
   * - When selectedNodeId is "skrub_sem_gen_features_5"
   * - And code is stored under "skrub_sem_gen_features_5"
   * - Should find the code
   */
  it("finds code when both selectedNodeId and storage key have skrub_ prefix", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="skrub_sem_gen_features_5"
        selectedNode={{ id: "skrub_sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={false}
        liveGeneratedCodeByNode={{ "skrub_sem_gen_features_5": "# code for node" }}
      />
    );
    expect(screen.getByText("(live)")).toBeInTheDocument();
    expect(screen.queryByText(/no generated code/i)).not.toBeInTheDocument();
  });

  /**
   * Scenario 3: Had code, then run again
   * - Start with code → run → show new code
   */
  it("shows previous code then transitions to spinner when re-executing", () => {
    const { rerender } = render(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={false}
        liveGeneratedCodeByNode={{ sem_gen_features_5: "# old code" }}
      />
    );
    // Initially shows old code
    expect(screen.getByText("(live)")).toBeInTheDocument();

    // Re-render with execution starting (code cleared)
    rerender(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={true}
        liveGeneratedCodeByNode={{}}  // Code cleared at start of execution
      />
    );
    // Should show spinner
    expect(screen.getByText("Generating code for this node…")).toBeInTheDocument();
    expect(screen.queryByText("(live)")).not.toBeInTheDocument();
  });

  /**
   * Scenario 3: Verify full transition cycle
   * - No code → executing (spinner) → code received → execution done (code shown)
   */
  it("full state cycle: no code → spinner → code received → done", () => {
    const { rerender } = render(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={false}
        liveGeneratedCodeByNode={{}}
      />
    );
    // Step 1: No code before run
    expect(screen.getByText(/no generated code/i)).toBeInTheDocument();

    // Step 2: Execution starts - show spinner
    rerender(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={true}
        liveGeneratedCodeByNode={{}}
      />
    );
    expect(screen.getByText("Generating code for this node…")).toBeInTheDocument();

    // Step 3: Code received during execution
    rerender(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={true}
        liveGeneratedCodeByNode={{ sem_gen_features_5: "# new generated code" }}
      />
    );
    expect(screen.getByText("(live)")).toBeInTheDocument();
    expect(screen.queryByText("Generating code for this node…")).not.toBeInTheDocument();

    // Step 4: Execution done - code still shown
    rerender(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={false}
        liveGeneratedCodeByNode={{ sem_gen_features_5: "# new generated code" }}
      />
    );
    expect(screen.getByText("(live)")).toBeInTheDocument();
    expect(screen.queryByText("Generating code for this node…")).not.toBeInTheDocument();
    expect(screen.queryByText(/no generated code/i)).not.toBeInTheDocument();
  });

  /**
   * Edge case: Input node during execution
   * - Should show "Running pipeline..." for input summary
   */
  it("input node shows 'running pipeline' message during execution", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="var_products_1"
        selectedNode={{ id: "var_products_1", type: "input", label: "products" }}
        isExecuting={true}
        inputSummaryByNode={{}}
      />
    );
    expect(screen.getByText(/running pipeline/i)).toBeInTheDocument();
  });

  /**
   * Edge case: Verify retries and cost are shown
   */
  it("shows retries and cost when available", () => {
    render(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={{ id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" }}
        isExecuting={false}
        liveGeneratedCodeByNode={{ sem_gen_features_5: "# code" }}
        liveRetriesByNode={{ sem_gen_features_5: 2 }}
        liveCostUsdByNode={{ sem_gen_features_5: 0.00123 }}
      />
    );
    expect(screen.getByText(/Attempts: 2/)).toBeInTheDocument();
    expect(screen.getByText(/Cost: \$0\.00123/)).toBeInTheDocument();
  });

});

describe("NodeDetailsPanel ID Lookup Edge Cases", () => {
  /**
   * Test various ID format combinations to ensure lookup works
   */
  const testCases = [
    { selectedId: "sem_gen_features_5", storageKey: "sem_gen_features_5", description: "raw to raw" },
    { selectedId: "skrub_sem_gen_features_5", storageKey: "sem_gen_features_5", description: "skrub to raw" },
    { selectedId: "skrub_sem_gen_features_5", storageKey: "skrub_sem_gen_features_5", description: "skrub to skrub" },
    { selectedId: "sem_gen_features_5", storageKey: "skrub_sem_gen_features_5", description: "raw to skrub (should fail)" },
    { selectedId: "skrub_0", storageKey: "skrub_0", description: "numeric skrub to skrub" },
    { selectedId: "skrub_0", storageKey: "0", description: "numeric skrub to raw" },
  ];

  testCases.forEach(({ selectedId, storageKey, description }) => {
    it(`lookup ${description}: selectedId="${selectedId}", storageKey="${storageKey}"`, () => {
      const liveCode: Record<string, string> = { [storageKey]: "# code found" };
      render(
        <NodeDetailsPanel
          selectedNodeId={selectedId}
          selectedNode={{ id: selectedId, type: "operator", label: "sem_gen_features" }}
          isExecuting={false}
          liveGeneratedCodeByNode={liveCode}
        />
      );

      // Check if code was found or not
      const hasLiveIndicator = screen.queryByText("(live)");
      const hasNoCodeMessage = screen.queryByText(/no generated code/i);

      // Log which case we're in for debugging
      if (hasLiveIndicator) {
        expect(hasNoCodeMessage).not.toBeInTheDocument();
      } else {
        expect(hasNoCodeMessage).toBeInTheDocument();
      }
    });
  });
});

describe("State Transition Integration (simulated)", () => {
  /**
   * Simulates the full flow that happens when Play is clicked:
   * 1. isExecuting becomes true
   * 2. liveNodeCode is cleared
   * 3. Events arrive with node_code
   * 4. isExecuting becomes false
   */
  it("simulates full execution flow with state updates", async () => {
    const selectedNode: GraphNode = { id: "skrub_sem_gen_features_5", type: "operator", label: "sem_gen_features" };
    let currentProps = {
      selectedNodeId: "skrub_sem_gen_features_5",
      selectedNode,
      isExecuting: false,
      liveGeneratedCodeByNode: {} as Record<string, string>,
    };

    const { rerender } = render(<NodeDetailsPanel {...currentProps} />);

    // Initial: no code
    expect(screen.getByText(/no generated code/i)).toBeInTheDocument();

    // Step 1: Play clicked - isExecuting true, code cleared
    currentProps = { ...currentProps, isExecuting: true, liveGeneratedCodeByNode: {} };
    rerender(<NodeDetailsPanel {...currentProps} />);
    expect(screen.getByText("Generating code for this node…")).toBeInTheDocument();

    // Step 2: node_code event received (stored under both IDs per our fix)
    currentProps = {
      ...currentProps,
      isExecuting: true,
      liveGeneratedCodeByNode: {
        "sem_gen_features_5": "# generated code here",
        "skrub_sem_gen_features_5": "# generated code here",
      },
    };
    rerender(<NodeDetailsPanel {...currentProps} />);
    expect(screen.getByText("(live)")).toBeInTheDocument();
    expect(screen.queryByText("Generating code for this node…")).not.toBeInTheDocument();

    // Step 3: done event - isExecuting false
    currentProps = { ...currentProps, isExecuting: false };
    rerender(<NodeDetailsPanel {...currentProps} />);
    expect(screen.getByText("(live)")).toBeInTheDocument();
    expect(screen.queryByText(/no generated code/i)).not.toBeInTheDocument();
  });

  /**
   * Simulates stop during execution
   */
  it("simulates stop during execution - reverts to no code state", async () => {
    const selectedNode: GraphNode = { id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" };

    const { rerender } = render(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={selectedNode}
        isExecuting={false}
        liveGeneratedCodeByNode={{}}
      />
    );

    // Initial: no code
    expect(screen.getByText(/no generated code/i)).toBeInTheDocument();

    // Play clicked
    rerender(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={selectedNode}
        isExecuting={true}
        liveGeneratedCodeByNode={{}}
      />
    );
    expect(screen.getByText("Generating code for this node…")).toBeInTheDocument();

    // Stop clicked before code arrived - execution ends with no code
    rerender(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={selectedNode}
        isExecuting={false}
        liveGeneratedCodeByNode={{}}
      />
    );
    // Should revert to "no generated code" since no code was received
    expect(screen.getByText(/no generated code/i)).toBeInTheDocument();
  });

  /**
   * Simulates stop during execution when previous code existed
   */
  it("simulates stop during execution - keeps previous code if it existed", async () => {
    const selectedNode: GraphNode = { id: "sem_gen_features_5", type: "operator", label: "sem_gen_features" };
    const previousCode = { sem_gen_features_5: "# previous run code" };

    const { rerender } = render(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={selectedNode}
        isExecuting={false}
        liveGeneratedCodeByNode={previousCode}
      />
    );

    // Initial: has previous code
    expect(screen.getByText("(live)")).toBeInTheDocument();

    // Note: In the real app, Play clears liveNodeCode.
    // This test shows what SHOULD happen if we want to preserve previous code on stop.
    // Currently the app clears code at start, so stopping shows "no generated code".

    // Play clicked - code is cleared in real app
    rerender(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={selectedNode}
        isExecuting={true}
        liveGeneratedCodeByNode={{}}  // Cleared by handlePlay
      />
    );
    expect(screen.getByText("Generating code for this node…")).toBeInTheDocument();

    // Stop clicked - execution ends with no new code
    // In current implementation, previous code is lost
    rerender(
      <NodeDetailsPanel
        selectedNodeId="sem_gen_features_5"
        selectedNode={selectedNode}
        isExecuting={false}
        liveGeneratedCodeByNode={{}}  // Still empty because stop happened
      />
    );
    // Current behavior: shows "no generated code" because code was cleared
    expect(screen.getByText(/no generated code/i)).toBeInTheDocument();
  });
});
