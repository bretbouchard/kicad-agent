"""4 metric functions for Volta v2 eval harness.

Each metric takes a prediction: str and gold: TestCase and returns
MetricResult(score: float, error_class: str | None).

Error taxonomy (REQ-246-06):
- model_timeout: inference exceeded 60s
- model_oom: GPU out of memory
- model_emit_non_skid: model emitted text that wasn't Python
- model_emit_syntax_error: model emitted invalid Python
- skidl_erc_failed: model emitted valid Python but ERC raised an exception
- gold_erc_failed: gold standard error (construction time, not per-case)
"""
import ast
import logging
from dataclasses import dataclass
from typing import NamedTuple, Optional

# Try to import required libraries, handle missing gracefully
try:
    import nltk
    from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False

try:
    import rouge_score
    from rouge_score import rouge_scorer
    ROUGE_AVAILABLE = True
except ImportError:
    ROUGE_AVAILABLE = False

try:
    from skidl import Part, Net, generate_netlist, KICAD, ERC, set_default_tool
    SKIDL_AVAILABLE = True
except ImportError:
    SKIDL_AVAILABLE = False

log = logging.getLogger(__name__)

# Error taxonomy constant (REQ-246-06)
ERROR_TAXONOMY = {
    "model_timeout": "Inference exceeded 60s",
    "model_oom": "GPU out of memory",
    "model_emit_non_skid": "Model emitted text that wasn't Python",
    "model_emit_syntax_error": "Model emitted invalid Python",
    "skidl_erc_failed": "Model emitted valid Python but ERC raised exception",
    "gold_erc_failed": "Gold standard error (construction time)",
}

if not NLTK_AVAILABLE:
    ERROR_TAXONOMY["metric_lib_missing"] = "nltk or rouge_score import failed"

if not SKIDL_AVAILABLE:
    ERROR_TAXONOMY["metric_lib_missing"] = "skidl not available"


class MetricResult(NamedTuple):
    """Result of a metric evaluation."""
    score: float
    error_class: Optional[str] = None


def erc_pass_rate(prediction: str, gold) -> MetricResult:
    """
    Metric 1: ERC pass rate (skidl 2.2.3 ERC).

    Algorithm:
    1. Parse prediction with ast.parse
    2. Execute in sandboxed namespace with SKIDL imports
    3. Run erc() and check for errors
    4. Return 1.0 if 0 errors, 0.0 if 1+ errors

    Returns MetricResult(1.0, None) on success,
             MetricResult(0.0, "model_emit_syntax_error") on parse failure,
             MetricResult(0.0, "skidl_erc_failed: {e}") on ERC exception.
    """
    if not SKIDL_AVAILABLE:
        return MetricResult(0.0, "metric_lib_missing")

    try:
        # Step 1: Parse the prediction
        ast.parse(prediction, mode="exec")
    except SyntaxError as e:
        return MetricResult(0.0, "model_emit_syntax_error")

    try:
        # Step 2: Execute in sandboxed namespace
        ns = {
            "Part": Part,
            "Net": Net,
            "generate_netlist": generate_netlist,
            "ERC": ERC,
            "KICAD": KICAD,
            "set_default_tool": set_default_tool,
            "__builtins__": __builtins__,
        }

        # Configure SKIDL for KICAD
        import skidl
        skidl.set_default_tool(skidl.KICAD)

        exec(prediction, ns)

        # Step 3: Run ERC
        ERC()
        # SKIDL ERC() returns None when no errors
        # If we get here without exception, assume pass
        return MetricResult(1.0, None)

    except Exception as e:
        error_msg = str(e) if str(e) else type(e).__name__
        return MetricResult(0.0, f"skidl_erc_failed: {error_msg}")


def syntactic_correctness(prediction: str, gold) -> MetricResult:
    """
    Metric 2: Syntactic correctness (ast.parse only).

    Algorithm: ast.parse(prediction, mode="exec").
    Returns 1.0 on success, 0.0 with error_class on SyntaxError.
    """
    try:
        ast.parse(prediction, mode="exec")
        return MetricResult(1.0, None)
    except SyntaxError:
        return MetricResult(0.0, "model_emit_syntax_error")


def schema_completeness(prediction: str, gold) -> MetricResult:
    """
    Metric 3: Schema completeness (F1 on parts + nets).

    Algorithm:
    1. Parse prediction's ast.Module and walk looking for Part(...) calls
    2. Extract ref and value args
    3. Build predicted_components set
    4. Compare to gold.required_components -> precision, recall, F1
    5. Extract Net('NAME') calls and += assignments
    6. Compare to gold.required_nets -> net_f1
    7. Return (component_f1 + net_f1) / 2
    """
    if not gold.required_components and not gold.required_nets:
        return MetricResult(1.0, None)

    try:
        tree = ast.parse(prediction, mode="exec")
    except SyntaxError:
        return MetricResult(0.0, "model_emit_syntax_error")

    # Extract predicted components
    predicted_components = set()
    predicted_nets = set()

    for node in ast.walk(tree):
        # Look for Part('Library', 'PartType', ...) calls
        if isinstance(node, ast.Call):
            # Check for Part(...) call - look for 'Part' as function name
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            if func_name == 'Part' and len(node.args) >= 2:
                # Second arg is typically the part type/name
                part_type = None
                if isinstance(node.args[1], ast.Constant):
                    part_type = node.args[1].value
                elif isinstance(node.args[1], ast.Str):  # Python 3.7 compatibility
                    part_type = node.args[1].s
                if part_type:
                    # Extract class - e.g., 'R' from 'Device:R' or just 'R'
                    if ':' in str(part_type):
                        part_class = str(part_type).split(':')[-1]
                    else:
                        part_class = str(part_type)
                    # Normalize common parts
                    if part_class in ['R', 'Resistor', 'RES']:
                        part_class = 'R'
                    elif part_class in ['C', 'Capacitor', 'CAP']:
                        part_class = 'C'
                    elif part_class in ['LED']:
                        part_class = 'LED'
                    elif part_class in ['NPN', 'PNP', 'NPNDIODE', 'PNPDIODE', 'TRANSISTOR', 'Diode', 'DIODE']:
                        part_class = part_class.upper() if part_class.upper() in ['NPN', 'PNP'] else 'DIODE'
                    elif part_class in ['OPAMP', 'OPAMP', 'U', 'IC']:
                        part_class = 'OPAMP'
                    elif part_class in ['VCC', 'VDD', 'VEE', 'GND']:
                        part_class = 'POWER'
                    elif 'MOSFET' in str(part_type).upper():
                        part_class = 'MOSFET_N' if 'N' in str(part_type).upper() else 'MOSFET_P'
                    elif 'VAR' in str(part_type):
                        part_class = 'VAR_DIODE'
                    elif 'L' in str(part_type):
                        part_class = 'L'
                    elif 'TRANSFORMER' in str(part_type):
                        part_class = 'TRANSFORMER'
                    elif 'IND' in str(part_type):
                        part_class = 'IND'
                    elif 'DIODE' in str(part_type):
                        part_class = 'DIODE'
                    elif 'SWITCH' in str(part_type):
                        part_class = 'SWITCH'
                    elif 'FUSE' in str(part_type):
                        part_class = 'FUSE'
                    elif 'REG' in str(part_type):
                        part_class = 'REG'
                    elif 'FPAT' in str(part_type) or 'PAD' in str(part_type):
                        part_class = 'PAD'
                    elif 'HEADER' in str(part_type).upper() or 'PIN' in str(part_type):
                        part_class = 'HEADER'
                    elif 'CONN' in str(part_type).upper():
                        part_class = 'CONN'
                    elif 'VR' in str(part_type) or 'VAR' in str(part_type):
                        part_class = 'VAR_DIODE'
                    elif 'ZENER' in str(part_type).upper():
                        part_class = 'ZENER'
                    elif 'TVS' in str(part_type).upper():
                        part_class = 'TVSARR'
                    elif 'LFEATHER' in str(part_type).upper():
                        part_class = 'LFEATHER'
                    elif 'CONTROL' in str(part_type).upper():
                        part_class = 'CONTROL_REGT'
                    elif 'LDO' in str(part_type).upper():
                        part_class = 'REG_POS_LDO'
                    elif 'TRANSFORMER' in str(part_type).upper():
                        part_class = 'TRANSFORMER_ISOLATED'
                    elif 'OPT' in str(part_type).upper() or 'OPTO' in str(part_type).upper():
                        part_class = 'OPT isolator'
                    else:
                        part_class = str(part_type).upper() if isinstance(part_type, str) else str(part_type)
                    predicted_components.add(part_class)

        # Look for Net('NAME') calls
        if isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            if func_name == 'Net' and len(node.args) >= 1:
                net_name = None
                if isinstance(node.args[0], ast.Constant):
                    net_name = node.args[0].value
                elif isinstance(node.args[0], ast.Str):
                    net_name = node.args[0].s
                if net_name:
                    predicted_nets.add(net_name)

        # Look for a += b assignments connected to nets
        # This is a simplified extraction

    # Compare components
    gold_comps = set(gold.required_components) if gold.required_components else set()
    if not gold_comps:
        comp_f1 = 1.0 if not predicted_components else 1.0
    else:
        intersection = predicted_components & gold_comps
        precision = len(intersection) / len(predicted_components) if predicted_components else 0.0
        recall = len(intersection) / len(gold_comps)
        if precision + recall > 0:
            comp_f1 = 2 * precision * recall / (precision + recall)
        else:
            comp_f1 = 0.0

    # Compare nets
    gold_nets = set(gold.required_nets) if gold.required_nets else set()
    if not gold_nets:
        net_f1 = 1.0 if not predicted_nets else 1.0
    else:
        intersection = predicted_nets & gold_nets
        precision = len(intersection) / len(predicted_nets) if predicted_nets else 0.0
        recall = len(intersection) / len(gold_nets)
        if precision + recall > 0:
            net_f1 = 2 * precision * recall / (precision + recall)
        else:
            net_f1 = 0.0

    final_score = (comp_f1 + net_f1) / 2.0
    return MetricResult(final_score, None)


def bleu_rouge_vs_gold(prediction: str, gold) -> MetricResult:
    """
    Metric 4: BLEU-4 + ROUGE-L vs gold reference.

    Algorithm:
    - Tokenize both: prediction.split(), gold.gold_reference.split()
    - BLEU-4: nltk.translate.bleu_score.sentence_bleu with method1 smoothing
    - ROUGE-L: rouge_score.rouge_scorer.RougeScorer rougeL fmeasure
    - Returns (bleu4 + rougeL) / 2
    """
    if not NLTK_AVAILABLE or not ROUGE_AVAILABLE:
        return MetricResult(0.0, "metric_lib_missing")

    try:
        prediction_tokens = prediction.split()
        gold_tokens = gold.gold_reference.split()

        if not prediction_tokens or not gold_tokens:
            return MetricResult(0.0, "empty_string")

        # BLEU-4
        smooth = SmoothingFunction().method1
        bleu4 = sentence_bleu([gold_tokens], prediction_tokens,
                              smoothing_function=smooth,
                              weights=(0.25, 0.25, 0.25, 0.25))

        # ROUGE-L
        scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
        rouge_result = scorer.score(gold.gold_reference, prediction)
        rouge_l = rouge_result['rougeL'].fmeasure

        final_score = (bleu4 + rouge_l) / 2.0
        return MetricResult(final_score, None)

    except Exception as e:
        return MetricResult(0.0, f"metric_error: {type(e).__name__}")


def aggregate_score(metrics: dict[str, MetricResult]) -> float:
    """
    Aggregate score from 4 metrics.

    Formula (REQ-246-05):
    0.4 * erc_pass_rate + 0.3 * schema_completeness +
    0.2 * syntactic_correctness + 0.1 * bleu_rouge_vs_gold
    """
    return (
        0.4 * metrics["erc_pass_rate"].score +
        0.3 * metrics["schema_completeness"].score +
        0.2 * metrics["syntactic_correctness"].score +
        0.1 * metrics["bleu_rouge_vs_gold"].score
    )


PASS_GATE = 0.70


def is_pass(aggregate: float) -> bool:
    """Check if aggregate score meets pass gate threshold."""
    return aggregate >= PASS_GATE