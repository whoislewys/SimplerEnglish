#!/usr/bin/env python3
"""Benchmark the simple-english skill variants across models.

For each model x condition x scenario, runs a headless `claude -p` call,
lints the output with ste_lint.py, and aggregates to results.json +
RESULTS.md. Resumable: existing raw result files are skipped.

Conditions are variant-aware: `baseline` (bare prompt) plus one condition per
entry in VARIANTS. The report shape follows the raw files that exist, so an
older single-variant results directory still rebuilds as before.

Requires: Claude Code CLI logged in. No API key needed.

Usage:
  python3 run_bench.py                     # full matrix
  python3 run_bench.py --smoke             # 1 model x 2 scenarios, all conditions
  python3 run_bench.py --report-only       # rebuild RESULTS.md from raw/
  python3 run_bench.py --judge             # blind pairwise judge pass (extra)
  python3 run_bench.py --results-dir results/ab-2026-08-14
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

import ste_lint

HERE = pathlib.Path(__file__).resolve().parent
SKILLS = HERE.parent / "skills"
DEFAULT_RESULTS_DIR = HERE / "results"
MODELS = [
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-opus-4-5-20251101",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
]
JUDGE_MODEL = "claude-opus-4-8"
BASELINE = "baseline"

# condition name -> SKILL.md path. Baseline is implicit and always run.
VARIANTS = {
    "skill-v1": SKILLS / "simple-english" / "SKILL.md",
    "skill-v2": SKILLS / "simple-english-v2" / "SKILL.md",
}
CONDITIONS = [BASELINE] + list(VARIANTS)

# Display labels for report tables. Legacy raw dirs use the bare name "skill".
LABELS = {
    BASELINE: "Baseline",
    "skill": "Skill",
    "skill-v1": "V1 (full skill)",
    "skill-v2": "V2 (one-line)",
}


def label(cond):
    return LABELS.get(cond, cond)


def call_claude(prompt, model, timeout=300):
    cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "json",
           "--disallowedTools",
           "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Skill"]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd="/tmp")
    if proc.returncode != 0:
        raise RuntimeError(f"{model}: {proc.stderr[:300]}")
    env = json.loads(proc.stdout)
    if isinstance(env, list):  # CLI >= 2.1 returns the message stream
        env = next(m for m in env if m.get("type") == "result")
    if env.get("is_error"):
        raise RuntimeError(f"{model}: {str(env.get('result'))[:300]}")
    usage = env.get("usage", {})
    return {
        "text": env.get("result", ""),
        "input_tokens": usage.get("input_tokens"),
        # The CLI reports uncached input separately from cache reads/writes; the
        # sum is what the model actually read, CLI system prompt included.
        "prompt_tokens": sum(usage.get(k) or 0 for k in (
            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
        "output_tokens": usage.get("output_tokens"),
        "duration_ms": env.get("duration_ms", int(1000 * (time.time() - t0))),
        "cost_usd": env.get("total_cost_usd"),
    }


def build_prompt(scenario, skill_text):
    """skill_text is None for the baseline condition."""
    if skill_text is None:
        return scenario["prompt"]
    return ("Follow these writing instructions exactly, including the self-check step:\n\n"
            + skill_text + "\n\n---\n\nTask: " + scenario["prompt"]
            + "\n\nReturn only the final text, no rule commentary.")


def skill_body(cond):
    """Body of a variant's SKILL.md with the YAML frontmatter removed."""
    text = VARIANTS[cond].read_text()
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()


def generate(models, scenarios, results_dir, conditions=None):
    conditions = conditions or CONDITIONS
    texts = {c: (None if c == BASELINE else VARIANTS[c].read_text()) for c in conditions}
    raw = results_dir / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    todo = [(m, c, s) for m in models for c in conditions for s in scenarios]
    for i, (model, cond, sc) in enumerate(todo, 1):
        out = raw / f"{model}__{cond}__{sc['id']}.json"
        if out.exists():
            continue
        print(f"[{i}/{len(todo)}] {model} {cond} {sc['id']}", flush=True)
        try:
            res = call_claude(build_prompt(sc, texts[cond]), model)
        except Exception as e:
            print(f"  FAILED: {e}", flush=True)
            continue
        res.update(model=model, condition=cond, scenario=sc["id"], type=sc["type"])
        res["lint"] = ste_lint.lint(res["text"], sc["type"])
        out.write_text(json.dumps(res, indent=2))
        time.sleep(2)


def load_rows(results_dir):
    return [json.loads(p.read_text())
            for p in sorted((results_dir / "raw").glob("*.json"))
            if "__judge" not in p.name]


def mean(values, digits=2):
    values = [v for v in values if v is not None]
    if not values:
        return None
    if digits == 0:
        return round(sum(values) / len(values))
    return round(sum(values) / len(values), digits)


def aggregate(results_dir):
    """Per-model table plus per-arm spend. Conditions come from the raw files."""
    rows = load_rows(results_dir)
    found = {r["condition"] for r in rows}
    conds = [c for c in CONDITIONS if c in found] + sorted(found - set(CONDITIONS))
    if BASELINE in conds:  # keep baseline first whatever the raw dir holds
        conds = [BASELINE] + [c for c in conds if c != BASELINE]
    variants = [c for c in conds if c != BASELINE]

    per_model = {}
    for r in rows:
        per_model.setdefault(r["model"], {c: [] for c in conds})[r["condition"]].append(r)

    table = []
    for model in [m for m in MODELS if m in per_model]:
        row = {"model": model}
        for cond in conds:
            runs = per_model[model][cond]
            if not runs:
                continue
            row[f"{cond}_viol_per_100w"] = mean(
                [r["lint"]["violations_per_100w"] for r in runs])
            row[f"{cond}_mean_sentence"] = mean(
                [r["lint"]["mean_sentence_words"] for r in runs], 1)
            row[f"{cond}_output_tokens"] = round(
                sum(r["output_tokens"] or 0 for r in runs) / len(runs))
            row[f"{cond}_cost_usd"] = mean([r.get("cost_usd") for r in runs], 4)
            row[f"{cond}_n"] = len(runs)
        b = row.get(f"{BASELINE}_viol_per_100w")
        for v in variants:
            s = row.get(f"{v}_viol_per_100w")
            if b and s is not None:
                row[f"reduction_pct_{v}"] = round(100 * (b - s) / b, 1)
        if len(variants) == 1 and f"reduction_pct_{variants[0]}" in row:
            row["reduction_pct"] = row[f"reduction_pct_{variants[0]}"]
        table.append(row)

    spend = {}
    for cond in conds:
        runs = [r for r in rows if r["condition"] == cond]
        if not runs:
            continue
        spend[cond] = {
            "n": len(runs),
            "mean_cost_usd": mean([r.get("cost_usd") for r in runs], 4),
            "mean_prompt_tokens": mean([r.get("prompt_tokens") for r in runs], 0),
            "mean_output_tokens": mean([r.get("output_tokens") for r in runs], 0),
        }
        if cond in VARIANTS:
            body = skill_body(cond)
            spend[cond]["skill_body_words"] = len(body.split())
            spend[cond]["skill_body_est_tokens"] = round(len(body) / 4)

    out = {"generated": time.strftime("%Y-%m-%d"), "models": table, "runs": len(rows)}
    if len(variants) > 1:  # keep the legacy results.json shape byte-identical
        out["conditions"] = conds
        out["spend"] = spend
    (results_dir / "results.json").write_text(json.dumps(out, indent=2))
    return table, conds, spend


def judge_summary(results_dir, variants):
    """Aggregate judge files into report lines, grouped per variant."""
    per_variant = {}
    for p in sorted((results_dir / "raw").glob("*__judge*.json")):
        d = json.loads(p.read_text())
        v = d.get("variant", "skill")
        o1 = d.get("order1_base_first")
        o2 = d.get("order2_variant_first") or d.get("order2_skill_first")
        if not o1 or not o2:
            continue
        agg = per_variant.setdefault(v, {"models": {}, "w": 0, "t": 0, "l": 0,
                                         "v_sum": 0.0, "b_sum": 0.0, "n": 0})
        skill = (o1["b_score"] + o2["a_score"]) / 2
        base = (o1["a_score"] + o2["b_score"]) / 2
        agg["n"] += 1
        agg["v_sum"] += skill
        agg["b_sum"] += base
        w = agg["models"].setdefault(d["model"], [0, 0, 0])
        if skill > base:
            agg["w"] += 1
            w[0] += 1
        elif skill == base:
            agg["t"] += 1
            w[1] += 1
        else:
            agg["l"] += 1
            w[2] += 1
    if not per_variant:
        return [], {}

    order = [v for v in variants if v in per_variant] or list(per_variant)
    legacy = order == ["skill"]
    lines = ["", "## Judge pass (blind pairwise)", ""]
    if legacy:
        lines += [
            f"For each model x scenario pair, {JUDGE_MODEL} scored the baseline text and",
            "the skill text on a 0-10 rubric, twice with the texts in both orders. The",
            "two scores were averaged to cancel position bias. The judge saw no labels.",
        ]
    else:
        lines += [
            f"For each variant x model x scenario pair, {JUDGE_MODEL} scored the baseline",
            "text and the variant text on a 0-10 rubric, twice with the texts in both",
            "orders. The two scores were averaged to cancel position bias. The judge saw",
            "no labels. Each variant was judged against the baseline only, never against",
            "the other variant.",
        ]
    for v in order:
        a = per_variant[v]
        name = "skill" if legacy else label(v)
        lines += [
            "",
            f"Result: the {name} output scored higher in {a['w']} of {a['n']} pairs, tied in",
            f"{a['t']}, and lost in {a['l']}. Mean rubric score: {a['v_sum'] / a['n']:.2f} "
            f"with the skill, {a['b_sum'] / a['n']:.2f} without.",
            "",
            f"| Model | {name} wins | Ties | Losses |" if not legacy
            else "| Model | Skill wins | Ties | Losses |",
            "|---|---|---|---|",
        ]
        for m in [m for m in MODELS if m in a["models"]]:
            w, t, l = a["models"][m]
            lines.append(f"| {m} | {w} | {t} | {l} |")
    glob = "*__judge__*.json" if legacy else "*__judge-*.json"
    if not legacy and len(order) > 1:
        base_scores = ", ".join(
            f"{label(v)} block {per_variant[v]['b_sum'] / per_variant[v]['n']:.2f}"
            for v in order)
        lines += [
            "",
            "Read the win rates within a variant, not across variants. The baseline texts",
            "are identical in every block, but the judge scored them differently depending",
            f"on the text they were paired with ({base_scores}). A contrast effect of that",
            "size means the variant-to-variant difference in win rate is weaker evidence",
            "than the linter numbers above.",
        ]
    lines += [
        "",
        "Caveats: one judge model, judged once per order. The judge is a Claude",
        "model and the texts are Claude output, so family bias is possible. Raw",
        f"judge files: {results_dir.name}/raw/{glob}. Reproduce with",
        "`python3 evals/run_bench.py --judge`.",
    ]
    stats = {v: per_variant[v] for v in order}
    return lines, stats


def warnings_block():
    return [
        "",
        "## Honest number warnings",
        "",
        "- The linter is a regex pass (see ste_lint.py header). It undercounts real STE",
        "  violations: no passive-voice or part-of-speech detection. It counts the same",
        "  way for both conditions, so the comparison is fair even where the absolute",
        "  numbers are low.",
        "- The skill condition sends SKILL.md in the prompt, so its input tokens are",
        "  higher by design. Output tokens are reported; draw your own conclusion.",
        "- One generation per cell. Re-run the matrix for variance; the runner is",
        "  resumable, delete results/raw to start fresh.",
        "- No tool can guarantee ASD-STE100 compliance, including this one.",
        "",
        "Reproduce: `python3 evals/run_bench.py` (Claude Code CLI, logged in).",
    ]


def report_legacy(table, results_dir):
    """The original single-variant report. Kept byte-identical on purpose."""
    ok = [r for r in table if "reduction_pct" in r]
    avg = round(sum(r["reduction_pct"] for r in ok) / max(1, len(ok)), 1)
    n = sum(r.get("baseline_n", 0) + r.get("skill_n", 0) for r in table)
    lines = [
        "# Benchmark results",
        "",
        f"**{avg}% fewer STE violations per 100 words with the skill, averaged across "
        f"{len(ok)} models x 8 tasks ({n} generations, measured).**",
        "",
        "| Model | Baseline viol/100w | Skill viol/100w | Reduction | Baseline sent. len | Skill sent. len | Output tok (base->skill) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in ok:
        lines.append(
            f"| {r['model']} | {r['baseline_viol_per_100w']} | {r['skill_viol_per_100w']} "
            f"| {r['reduction_pct']}% | {r['baseline_mean_sentence']} | {r['skill_mean_sentence']} "
            f"| {r['baseline_output_tokens']} -> {r['skill_output_tokens']} |")
    lines += judge_summary(results_dir, ["skill"])[0]
    lines += warnings_block()
    return lines


CRITERION_PP = 5.0


def report_ab(table, variants, spend, results_dir):
    """A/B report: every variant against the baseline, then variant vs variant."""
    avg = {}
    for v in variants:
        vals = [r[f"reduction_pct_{v}"] for r in table if f"reduction_pct_{v}" in r]
        if vals:
            avg[v] = round(sum(vals) / len(vals), 1)
    headline = " | ".join(f"{label(v)}: {avg[v]}%" for v in variants if v in avg)
    n = sum(sum(r.get(f"{c}_n", 0) for c in [BASELINE] + variants) for r in table)

    lines = [
        "# Benchmark results: skill variants A/B",
        "",
        f"**Fewer STE violations per 100 words vs baseline — {headline}** "
        f"({n} generations, measured).",
        "",
        "Pre-registered criterion: the one-line V2 skill passes if its mean "
        f"violation-reduction-vs-baseline is within {CRITERION_PP:.0f} percentage points "
        "of the full V1 skill's, on the same model x scenario matrix.",
        "",
        "## Violations per 100 words",
        "",
        "| Model | " + " | ".join(f"{label(c)} viol/100w" for c in [BASELINE] + variants)
        + " | " + " | ".join(f"{label(v)} reduction" for v in variants) + " |",
        "|" + "---|" * (1 + len([BASELINE] + variants) + len(variants)),
    ]
    for r in table:
        cells = [r["model"]]
        cells += [f"{r.get(f'{c}_viol_per_100w', '-')}" for c in [BASELINE] + variants]
        cells += [f"{r[f'reduction_pct_{v}']}%" if f"reduction_pct_{v}" in r else "-"
                  for v in variants]
        lines.append("| " + " | ".join(cells) + " |")
    if avg:
        lines.append("| **mean** | " + " | ".join(
            ["-"] * len([BASELINE] + variants)
            + [f"**{avg.get(v, '-')}%**" for v in variants]) + " |")

    lines += [
        "",
        "## Mean sentence length (words)",
        "",
        "| Model | " + " | ".join(label(c) for c in [BASELINE] + variants) + " |",
        "|" + "---|" * (1 + len([BASELINE] + variants)),
    ]
    for r in table:
        lines.append("| " + " | ".join(
            [r["model"]] + [f"{r.get(f'{c}_mean_sentence', '-')}"
                            for c in [BASELINE] + variants]) + " |")

    judge_lines, judge_stats = judge_summary(results_dir, variants)
    lines += judge_lines

    lines += [
        "",
        "## Token and dollar spend",
        "",
        "Skill body = SKILL.md with the YAML frontmatter removed. Its token count is an",
        "estimate at 4 characters per token, not a tokenizer run. Prompt tokens are the",
        "measured sum of uncached input, cache writes, and cache reads per cell; they",
        "include the CLI's own system prompt (~13k), so read the difference between arms,",
        "not the absolute number. Cost and token figures per arm are means over every",
        "cell in that arm, as reported by the Claude Code CLI (`total_cost_usd`, `usage`).",
        "",
        "| Arm | Skill body words | Skill body est. tokens | Mean prompt tok/cell | "
        "Mean output tok/cell | Mean $/cell |",
        "|---|---|---|---|---|---|",
    ]
    for c in [BASELINE] + variants:
        s = spend.get(c)
        if not s:
            continue
        lines.append(
            f"| {label(c)} | {s.get('skill_body_words', '-')} | "
            f"{s.get('skill_body_est_tokens', '-')} | {s['mean_prompt_tokens']} | "
            f"{s['mean_output_tokens']} | ${s['mean_cost_usd']} |")

    lines += ["", "## Verdict", ""]
    if "skill-v1" in avg and "skill-v2" in avg:
        gap = round(avg["skill-v2"] - avg["skill-v1"], 1)
        passed = abs(gap) <= CRITERION_PP
        v1s, v2s = spend.get("skill-v1", {}), spend.get("skill-v2", {})
        lines += [
            f"- Reduction vs baseline: V1 {avg['skill-v1']}%, V2 {avg['skill-v2']}%. "
            f"Gap: {gap:+.1f} percentage points.",
            f"- Pre-registered {CRITERION_PP:.0f}-point criterion: "
            f"**{'MET' if passed else 'NOT MET'}**.",
        ]
        if v1s.get("skill_body_est_tokens") and v2s.get("skill_body_est_tokens"):
            lines.append(
                f"- Prompt cost: V2's body is ~{v1s['skill_body_est_tokens'] - v2s['skill_body_est_tokens']} "
                f"estimated tokens lighter than V1's "
                f"({v1s['skill_body_est_tokens']} -> {v2s['skill_body_est_tokens']}); "
                f"measured mean prompt tokens per cell: {v1s.get('mean_prompt_tokens')} -> "
                f"{v2s.get('mean_prompt_tokens')}; mean cost per cell: "
                f"${v1s.get('mean_cost_usd')} -> ${v2s.get('mean_cost_usd')}.")
        for v in ("skill-v1", "skill-v2"):
            a = judge_stats.get(v)
            if a:
                lines.append(
                    f"- Judge, {label(v)}: won {a['w']}/{a['n']} pairs, mean score "
                    f"{a['v_sum'] / a['n']:.2f} vs baseline {a['b_sum'] / a['n']:.2f}.")
    else:
        lines.append("- Both variants are needed for the A/B verdict; "
                     f"present: {', '.join(variants) or 'none'}.")

    lines += warnings_block()
    lines += [
        "",
        "- Both variants use the identical prompt wrapper, including the phrase "
        "\"including the self-check step\". V2's body defines no self-check step; the",
        "  wrapper was left unchanged so the only difference between the arms is the",
        "  skill body.",
        f"- This run: `python3 evals/run_bench.py --results-dir {results_dir.name}` "
        "(and `--judge`).",
    ]
    return lines


def report(table, conds, spend, results_dir):
    variants = [c for c in conds if c != BASELINE]
    if variants == ["skill"]:
        lines = report_legacy(table, results_dir)
    else:
        lines = report_ab(table, variants, spend, results_dir)
    (results_dir / "RESULTS.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))


def judge(scenarios, results_dir, models=None, conditions=None):
    """Blind pairwise: rubric-score each variant against baseline, both orders."""
    import itertools
    models = models or MODELS
    variants = [c for c in (conditions or CONDITIONS) if c != BASELINE]
    raw = results_dir / "raw"
    rubric = ("Score the two texts A and B on: (1) can a tired non-native reader "
              "misread any sentence, (2) is every instruction executable as written, "
              "(3) filler or slop present. Reply with JSON only: "
              '{"a_score": 0-10, "b_score": 0-10}')
    for variant, model, sc in itertools.product(variants, models, scenarios):
        pair = {}
        for cond in (BASELINE, variant):
            p = raw / f"{model}__{cond}__{sc['id']}.json"
            if p.exists():
                pair[cond] = json.loads(p.read_text())["text"]
        if len(pair) != 2:
            continue
        out = raw / f"{model}__judge-{variant}__{sc['id']}.json"
        if out.exists():
            continue
        scores = []
        for a, b in ((pair[BASELINE], pair[variant]), (pair[variant], pair[BASELINE])):
            res = call_claude(f"{rubric}\n\nTEXT A:\n{a}\n\nTEXT B:\n{b}", JUDGE_MODEL)
            try:
                scores.append(json.loads(res["text"].strip().strip("`json\n")))
            except json.JSONDecodeError:
                scores.append(None)
        out.write_text(json.dumps({"model": model, "scenario": sc["id"],
                                   "variant": variant,
                                   "order1_base_first": scores[0],
                                   "order2_variant_first": scores[1]}, indent=2))
        print(f"judged {variant} {model} {sc['id']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true",
                        help="1 model x 2 scenarios, every condition")
    parser.add_argument("--judge", action="store_true", help="run the judge pass only")
    parser.add_argument("--report-only", action="store_true",
                        help="rebuild results.json + RESULTS.md from raw/")
    parser.add_argument("--results-dir", type=pathlib.Path, default=DEFAULT_RESULTS_DIR,
                        help=f"result directory (default: {DEFAULT_RESULTS_DIR})")
    args = parser.parse_args()
    results_dir = args.results_dir
    if not results_dir.is_absolute():
        results_dir = HERE / results_dir

    scenarios = json.loads((HERE / "scenarios.json").read_text())
    if args.judge:
        judge(scenarios, results_dir)
    elif args.smoke:
        generate(["claude-sonnet-4-6"], scenarios[:2], results_dir)
    elif not args.report_only:
        generate(MODELS, scenarios, results_dir)
    table, conds, spend = aggregate(results_dir)
    report(table, conds, spend, results_dir)


if __name__ == "__main__":
    main()
