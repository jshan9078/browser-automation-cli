#!/usr/bin/env python3
"""Score a run with BU Bench V1's judge: gemini-2.5-flash + their EXACT judge prompt/rubric/schema
(copied verbatim from browser-use/benchmark judge.py). Uses the official google-genai SDK so we don't
need to install browser_use. Reads raw/<task_id>.json, writes results/<task_id>.json.

  python3 judge_runner.py <task_id>

Env: GOOGLE_API_KEY (required — get one at aistudio.google.com/apikey; matches run_eval.py's judge).
"""
import base64, json, os, sys, time
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
RAW = HERE / os.environ.get("RAW_DIR", "raw"); RES = HERE / os.environ.get("RES_DIR", "results"); RES.mkdir(exist_ok=True)
# BU Bench used "gemini-2.5-flash". It's deprecated on AI Studio for new users (use Vertex to keep it),
# so this is overridable. For PARITY with their published numbers, use gemini-2.5-flash (via Vertex);
# only fall back to e.g. gemini-3.6-flash if 2.5-flash is unavailable — and disclose the judge change.
JUDGE_MODEL = os.environ.get("JUDGE_MODEL", "gemini-2.5-flash")
MAX_IMAGES = 10
# BU's judge is ChatGoogle(model="gemini-2.5-flash") with library DEFAULTS (verified from browser-use
# 0.11.5 source): temperature=0.5, dynamic thinking (thinking_budget=-1), structured output via
# response_schema=JudgementResult + response_mime_type=application/json, no seed. We replicate that
# per-call config EXACTLY, then wrap N independent calls in a majority vote to cut single-run noise
# (BU reduced the same noise by running the whole suite multiple times → their chart error bars).
JUDGE_VOTES = int(os.environ.get("JUDGE_VOTES", "3"))   # 3 judge evals per ONE agent run → stable verdict (judge-only variance). BU instead did 5 AGENT runs judged 1x each (agent+judge variance).
JUDGE_TEMPERATURE = float(os.environ.get("JUDGE_TEMPERATURE", "0.5"))


class JudgementResult(BaseModel):   # field order matches their judge.py JudgementResult
    reasoning: Optional[str] = None
    verdict: bool
    failure_reason: Optional[str] = None
    impossible_task: bool = False
    reached_captcha: bool = False


def _trunc(s, n=40000):
    s = s or ""
    return s if len(s) <= n else s[:n]


def build_prompts(task, final_result, agent_steps, ground_truth, n_images):
    gt_section = ""
    if ground_truth:
        gt_section = """
**GROUND TRUTH VALIDATION (HIGHEST PRIORITY):**
The <ground_truth> section contains verified correct information for this task. This can be:
- **Evaluation criteria**: Specific conditions that must be met (e.g., "The success popup should show up", "Must extract exactly 5 items")
- **Factual answers**: The correct answer to a question or information retrieval task (e.g. "10/11/24", "Paris")
- **Expected outcomes**: What should happen after task completion (e.g., "Google Doc must be created", "File should be downloaded")

The ground truth takes ABSOLUTE precedence over all other evaluation criteria. If the ground truth is not satisfied by the agent's execution and final response, the verdict MUST be false.
"""
    system_prompt = f"""You are an expert judge evaluating browser automation agent performance.

<evaluation_framework>
{gt_section}
**PRIMARY EVALUATION CRITERIA (in order of importance):**
1. **Task Satisfaction (Most Important)**: Did the agent accomplish what the user asked for? Break down the task into the key criteria and evaluate if the agent all of them. Focus on user intent and final outcome.
2. **Output Quality**: Is the final result in the correct format and complete? Does it match exactly what was requested?
3. **Tool Effectiveness**: Did the browser interactions work as expected? Were tools used appropriately? How many % of the tools failed?
4. **Agent Reasoning**: Quality of decision-making, planning, and problem-solving throughout the trajectory.
5. **Browser Handling**: Navigation stability, error recovery, and technical execution. If the browser crashes, does not load or a captcha blocks the task, the score must be very low.

**VERDICT GUIDELINES:**
- true: Task completed as requested, human-like execution, all of the users criteria were met and the agent did not make up any information.
- false: Task not completed, or only partially completed.

**Examples of task completion verdict:**
- If task asks for 10 items and agent finds 4 items correctly: false
- If task completed to full user requirements but with some errors to improve in the trajectory: true
- If task impossible due to captcha/login requirements: false
- If the trajectory is ideal and the output is perfect: true
- If the task asks to search all headphones in amazon under $100 but the agent searches all headphones and the lowest price is $150: false
- If the task asks to research a property and create a google doc with the result but the agents only returns the results in text: false
- If the task asks to complete an action on the page, and the agent reports that the action is completed but the screenshot or page shows the action is not actually complete: false
- If the task asks to use a certain tool or site to complete the task but the agent completes the task without using it: false
- If the task asks to look for a section of a page that does not exist: false
- If the agent concludes the task is impossible but it is not: false
- If the agent concludes the task is impossible and it truly is impossible: false
- If the agent is unable to complete the task because no login information was provided and it is truly needed to complete the task: false

**FAILURE CONDITIONS (automatically set verdict to false):**
- Blocked by captcha or missing authentication
- Output format completely wrong or missing
- Infinite loops or severe technical failures
- Critical user requirements ignored
- Page not loaded
- Browser crashed
- Agent could not interact with required UI elements
- The agent moved on from a important step in the task without completing it
- The agent made up content that is not in the screenshot or the page state
- The agent calls done action before completing all key points of the task

**IMPOSSIBLE TASK DETECTION:**
Set `impossible_task` to true when the task fundamentally could not be completed due to:
- Vague or ambiguous task instructions that cannot be reasonably interpreted
- Website genuinely broken or non-functional (be conservative - temporary issues don't count)
- Required links/pages truly inaccessible (404, 403, etc.)
- Task requires authentication/login but no credentials were provided
- Task asks for functionality that doesn't exist on the target site
- Other insurmountable external obstacles beyond the agent's control

Do NOT mark as impossible if:
- Agent made poor decisions but task was achievable
- Temporary page loading issues that could be retried
- Agent didn't try the right approach
- Website works but agent struggled with it

**CAPTCHA DETECTION:**
Set `reached_captcha` to true if:
- Screenshots show captcha challenges (reCAPTCHA, hCaptcha, etc.)
- Agent reports being blocked by bot detection
- Error messages indicate captcha/verification requirements
- Any evidence the agent encountered anti-bot measures during execution

**IMPORTANT EVALUATION NOTES:**
- **evaluate for action** - For each key step of the trace, double check whether the action that the agent tried to performed actually happened. If the required action did not actually occur, the verdict should be false.
- **screenshot is not entire content** - The agent has the entire DOM content, but the screenshot is only part of the content. If the agent extracts information from the page, but you do not see it in the screenshot, you can assume this information is there.
- **Penalize poor tool usage** - Wrong tools, inefficient approaches, ignoring available information.
- **ignore unexpected dates and times** - These agent traces are from varying dates, you can assume the dates the agent uses for search or filtering are correct.
- **IMPORTANT**: be very picky about the user's request - Have very high standard for the agent completing the task exactly to the user's request.
- **IMPORTANT**: be initially doubtful of the agent's self reported success, be sure to verify that its methods are valid and fulfill the user's desires to a tee.

</evaluation_framework>

<response_format>
Respond with EXACTLY this JSON structure (no additional text before or after):

{{
	"reasoning": "Breakdown of user task into key points. Detailed analysis covering: what went well, what didn't work, trajectory quality assessment, tool usage evaluation, output quality review, and overall user satisfaction prediction.",
	"verdict": true or false,
	"failure_reason": "Max 5 sentences explanation of why the task was not completed successfully in case of failure. If verdict is true, use an empty string.",
	"impossible_task": true or false,
	"reached_captcha": true or false
}}
</response_format>
"""
    gt_prompt = f"\n<ground_truth>\n{ground_truth}\n</ground_truth>\n" if ground_truth else ""
    user_prompt = f"""
<task>
{_trunc(task) or 'No task provided'}
</task>
{gt_prompt}
<agent_trajectory>
{_trunc(chr(10).join(agent_steps)) or 'No agent trajectory provided'}
</agent_trajectory>

<final_result>
{_trunc(final_result) or 'No final result provided'}
</final_result>

{n_images} screenshots from execution are attached.

Evaluate this agent execution given the criteria and respond with the exact JSON structure requested."""
    return system_prompt, user_prompt


def _load_env_keys():
    """Auto-load Google judge creds from repo-root .env if not already exported."""
    envf = Path(__file__).resolve().parents[2] / ".env"
    if not envf.exists():
        return
    for line in envf.read_text().splitlines():
        line = line.strip()
        for k in ("GOOGLE_API_KEY", "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_GENAI_USE_VERTEXAI"):
            if (line.startswith(f"{k}=") or line.startswith(f"export {k}=")) and not os.environ.get(k):
                os.environ[k] = line.split("=", 1)[1].strip().strip('"').strip("'")


def main():
    from google import genai
    from google.genai import types
    _load_env_keys()
    task_id = sys.argv[1]
    b = json.loads((RAW / f"{task_id}.json").read_text())

    # last N unique screenshots (dedupe preserving order), like their judge
    b64s = []
    for p in b.get("screenshots", []):
        # resolve relative to THIS RAW dir (bundles synced from a remote runner store absolute remote
        # paths like /home/ubuntu/...; the files actually live at RAW/shots/<task_id>/<basename>)
        local = RAW / "shots" / task_id / Path(p).name
        src = local if local.exists() else Path(p)
        try:
            b64s.append(base64.b64encode(src.read_bytes()).decode())
        except Exception:
            pass
    seen = set(); uniq = [s for s in reversed(b64s) if not (s in seen or seen.add(s))]
    selected = list(reversed(uniq[:MAX_IMAGES]))

    system_prompt, user_prompt = build_prompts(
        b["confirmed_task"], b.get("agent_result_text") or b.get("final_answer") or "",
        b.get("agent_steps", []), b.get("ground_truth"), len(selected))

    # Vertex (GCP credits, via ADC) when GOOGLE_CLOUD_PROJECT is set; else AI Studio API key.
    if os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"):
        client = genai.Client(vertexai=True, project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                              location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    else:
        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    parts = [types.Part.from_text(text=user_prompt)]
    for s in selected:
        parts.append(types.Part.from_bytes(data=base64.b64decode(s), mime_type="image/png"))
    # per-call config identical to BU's ChatGoogle(gemini-2.5-flash) judge
    cfg = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=JUDGE_TEMPERATURE,
        thinking_config=types.ThinkingConfig(thinking_budget=-1),   # dynamic thinking (their default)
        response_mime_type="application/json",
        response_schema=JudgementResult,
    )

    def judge_once():
        # retry with backoff on transient API errors (429 rate-limit / 503) so a throttle never
        # becomes a spurious verdict. Raises only if all attempts fail.
        last = None
        for attempt in range(6):
            try:
                resp = client.models.generate_content(model=JUDGE_MODEL, contents=parts, config=cfg)
                raw = (resp.text or "").strip()
                try:
                    return json.loads(raw)
                except Exception:
                    raw2 = raw.strip("`").split("json", 1)[-1] if "json" in raw[:10] else raw
                    return json.loads(raw2)
            except Exception as e:
                last = e; s = str(e)
                if any(k in s for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
                    time.sleep(min(60, 3 * (2 ** attempt)))  # 3,6,12,24,48,60s
                    continue
                time.sleep(2)
        raise last

    votes = []
    for _ in range(JUDGE_VOTES):
        try:
            votes.append(judge_once())
        except Exception as e:
            # EXCLUDE an errored call — never count an API failure as a False verdict
            print(f"judge vote errored (excluded): {e}", file=sys.stderr)
    if not votes:
        print("all judge votes failed (rate-limited) — NOT writing a result; retry later", file=sys.stderr)
        sys.exit(2)
    verdicts = [bool(v.get("verdict")) for v in votes]
    n_true = sum(verdicts)
    verdict = n_true > len(verdicts) / 2                     # strict majority (2/3 for the default)
    maj = lambda key: sum(1 for v in votes if v.get(key)) > len(votes) / 2   # majority flags
    rep = next((v for v in votes if bool(v.get("verdict")) == verdict), votes[0])  # representative reasoning

    r = {"task_id": task_id, "category": b.get("category"), "model": b.get("model"),
         "effort": b.get("effort"), "verdict": verdict, "score": 1 if verdict else 0,
         "votes": verdicts, "n_true": n_true, "n_votes": len(verdicts),
         "judge_model": JUDGE_MODEL, "judge_temperature": JUDGE_TEMPERATURE,
         "impossible_task": maj("impossible_task"), "reached_captcha": maj("reached_captcha"),
         "failure_reason": rep.get("failure_reason"), "reasoning": rep.get("reasoning"),
         "all_reasonings": [v.get("reasoning") for v in votes],
         "final_answer": b.get("final_answer"), "ground_truth": b.get("ground_truth"),
         "agent_tokens": b.get("agent_tokens"), "cli_calls": b.get("cli_calls"),
         "wall_s": b.get("wall_s"), "cost_usd": b.get("cost_usd"), "n_screenshots": len(selected)}
    (RES / f"{task_id}.json").write_text(json.dumps(r, indent=1))
    print(f"[{b.get('category')}] {task_id}  {'PASS' if verdict else 'FAIL'}  votes={verdicts} ({n_true}/{len(verdicts)})  answer={b.get('final_answer')!r}")


if __name__ == "__main__":
    main()
