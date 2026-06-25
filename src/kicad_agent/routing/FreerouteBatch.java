import app.freerouting.board.BasicBoard;
import app.freerouting.board.RoutingBoard;
import app.freerouting.io.specctra.DsnReader;
import app.freerouting.io.specctra.DsnReadResult;
import app.freerouting.io.specctra.DsnWriter;
import app.freerouting.autoroute.BatchAutorouter;
import app.freerouting.core.RoutingJob;
import app.freerouting.core.StoppableThread;
import app.freerouting.settings.RouterSettings;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.nio.file.Files;

/**
 * Headless Freerouting batch auto-router for KiCad DSN files.
 *
 * Usage: java -cp freerouting.jar FreerouteBatch <input.dsn> <output.ses> [passes] [snap_angle]
 *
 * snap_angle: "none" (default), "fortyfive_degree", or "ninety_degree".
 *   Phase 99-03 SC-5: Freerouting v2.2.4's BatchAutorouter does NOT honor the
 *   DSN (control (snap_angle ...)) directive. To make 45° / 90° modes actually
 *   produce different routing, we configure per-layer preferred directions:
 *     - fortyfive_degree: alternate horizontal/vertical per layer (classic
 *       2-layer 45° routing — F.Cu horizontal, B.Cu vertical).
 *     - ninety_degree: same direction on all layers (pure Manhattan).
 *     - none: leave preferred directions unset (router chooses freely).
 */
public class FreerouteBatch {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("Usage: java -cp freerouting.jar FreerouteBatch <input.dsn> <output.ses> [passes] [snap_angle]");
            System.exit(1);
        }

        String inputDsn = args[0];
        String outputSes = args[1];
        int passes = args.length > 2 ? Integer.parseInt(args[2]) : 25;
        String snapAngle = args.length > 3 ? args[3] : "none";

        System.out.println("Loading DSN: " + inputDsn);

        DsnReadResult result = DsnReader.readBoard(
            new FileInputStream(inputDsn),
            null, null
        );

        if (result instanceof DsnReadResult.Success) {
            BasicBoard board = ((DsnReadResult.Success) result).board();
            RoutingBoard routingBoard = (RoutingBoard) board;  // actual runtime type
            int layerCount = board.get_layer_count();
            System.out.println("Board loaded: " + layerCount + " layers");

            // Count connectable items (incomplete connections)
            int totalIncomplete = 0;
            int netsWithIncomplete = 0;
            for (int i = 1; i < 1000; i++) {
                int count = board.connectable_item_count(i);
                if (count > 0) {
                    totalIncomplete += count;
                    netsWithIncomplete++;
                }
            }
            System.out.println("Incomplete: " + totalIncomplete + " items in " + netsWithIncomplete + " nets");

            // Configure router via RoutingJob
            RoutingJob job = new RoutingJob();
            job.name = "analog-board";
            job.board = routingBoard;
            job.routerSettings = new RouterSettings(routingBoard);
            job.routerSettings.enabled = true;
            job.routerSettings.algorithm = RouterSettings.ALGORITHM_CURRENT;
            job.routerSettings.maxPasses = passes;
            job.routerSettings.vias_allowed = true;
            job.routerSettings.automatic_neckdown = true;
            job.routerSettings.maxThreads = 1;
            job.routerSettings.applyBoardSpecificOptimizations(routingBoard);

            // Scoring must be initialized separately.
            // Rule 1 fix: Freerouting v2.2.4's RouterScoringSettings default
            // constructor leaves all Float/Integer fields null, causing NPE in
            // BoardStatistics.calculateScore. Initialize ALL scoring fields.
            if (job.routerSettings.trace_pull_tight_accuracy == null) {
                job.routerSettings.trace_pull_tight_accuracy = 5;
            }
            if (job.routerSettings.scoring == null) {
                job.routerSettings.scoring = new app.freerouting.settings.RouterScoringSettings();
            }
            if (job.routerSettings.scoring.startRipupCosts == null) {
                job.routerSettings.scoring.startRipupCosts = 1;
            }
            if (job.routerSettings.scoring.viaCosts == null) {
                job.routerSettings.scoring.viaCosts = 1;
            }
            if (job.routerSettings.scoring.planeViaCosts == null) {
                job.routerSettings.scoring.planeViaCosts = 2;
            }
            if (job.routerSettings.scoring.unroutedNetPenalty == null) {
                job.routerSettings.scoring.unroutedNetPenalty = 100f;
            }
            if (job.routerSettings.scoring.clearanceViolationPenalty == null) {
                job.routerSettings.scoring.clearanceViolationPenalty = 50f;
            }
            if (job.routerSettings.scoring.bendPenalty == null) {
                job.routerSettings.scoring.bendPenalty = 10f;
            }
            if (job.routerSettings.optimizer == null) {
                job.routerSettings.optimizer = new app.freerouting.settings.RouterOptimizerSettings();
            }

            // Phase 99-03 SC-5: configure per-layer preferred directions based
            // on snap_angle. Freerouting v2.2.4's BatchAutorouter ignores the
            // DSN (control (snap_angle ...)) directive, so we set it here via
            // the RouterSettings API. isPreferredDirectionHorizontalOnLayer is
            // a transient boolean[] indexed by physical layer number.
            if (snapAngle.equals("fortyfive_degree") || snapAngle.equals("ninety_degree")) {
                int lc = routingBoard.get_layer_count();
                job.routerSettings.isPreferredDirectionHorizontalOnLayer = new boolean[lc];
                for (int li = 0; li < lc; li++) {
                    // fortyfive_degree: alternate direction per layer
                    //   (layer 0 horizontal, layer 1 vertical, ...) -> 45° routes
                    // ninety_degree: all layers same direction -> pure Manhattan
                    boolean horizontal;
                    if (snapAngle.equals("fortyfive_degree")) {
                        horizontal = (li % 2 == 0);
                    } else {
                        horizontal = true;
                    }
                    job.routerSettings.isPreferredDirectionHorizontalOnLayer[li] = horizontal;
                    job.routerSettings.set_preferred_direction_is_horizontal(li, horizontal);
                    // Penalize going against the preferred direction.
                    job.routerSettings.set_preferred_direction_trace_costs(li, 1.0);
                    job.routerSettings.set_against_preferred_direction_trace_costs(li, 5.0);
                }
                System.out.println("Configured " + snapAngle + " preferred directions across " + lc + " layers");
            }

            System.out.println("Starting auto-route (" + passes + " passes)...");
            long startTime = System.currentTimeMillis();

            // Create a non-stop StoppableThread for the job
            StoppableThread thread = new StoppableThread() {
                @Override protected void thread_action() {}
            };
            job.thread = thread;

            BatchAutorouter autorouter = new BatchAutorouter(job);
            boolean completed = autorouter.runBatchLoop();

            long elapsed = System.currentTimeMillis() - startTime;
            System.out.println("Auto-route " + (completed ? "completed" : "stopped") +
                             " in " + (elapsed / 1000) + "s");

            // Re-count
            int remainingIncomplete = 0;
            int remainingNets = 0;
            for (int i = 1; i < 1000; i++) {
                int count = board.connectable_item_count(i);
                if (count > 0) {
                    remainingIncomplete += count;
                    remainingNets++;
                }
            }
            System.out.println("Remaining incomplete: " + remainingIncomplete + " items in " + remainingNets + " nets");
            System.out.println("Routed: " + (totalIncomplete - remainingIncomplete) + " connections");

            // Write SES
            System.out.println("Writing SES: " + outputSes);
            DsnWriter.write(board, new FileOutputStream(outputSes), "KiCad", false);
            System.out.println("Done.");

        } else if (result instanceof DsnReadResult.ParseError) {
            System.err.println("Parse error");
            System.exit(2);
        } else if (result instanceof DsnReadResult.OutlineMissing) {
            System.err.println("Outline missing in DSN");
            System.exit(3);
        } else if (result instanceof DsnReadResult.IoError) {
            System.err.println("IO error");
            System.exit(4);
        } else {
            System.err.println("Unknown result: " + result.getClass().getName());
            System.exit(5);
        }
    }
}
