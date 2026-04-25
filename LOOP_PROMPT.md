# Atlas Phase 2 Implementation Loop Prompt

Paste the contents of the **LOOP COMMAND** block below into Claude Code to start
the autonomous Phase 2 build. The prompt is engineered for `/loop` dynamic-pacing
mode — Claude self-paces between iterations.

---

## LOOP COMMAND

```
/loop You are continuing Phase 2 implementation of Atlas — the open-source local-first cognitive memory system. Your job is to advance one Phase 2 task to completion per iteration, then schedule your next wakeup based on remaining work.

REPO: /Users/richardschefren/Projects/atlas/build/atlas (git initialized, master branch)
NEO4J: bolt://localhost:7687, user=neo4j, password=atlasdev (already running via docker compose)
SPECS: /Users/richardschefren/Obsidian/Active-Brain/00 Projects/World Model Research/05*, 06, 07, 08
TASKS: TaskList — work in numerical order on tasks #18 onward (#17 is complete)

ITERATION PROTOCOL — execute every wake:

1. ORIENT (read-only, ~2 min)
   - Run: cd ~/Projects/atlas/build/atlas && git log --oneline | head -10
   - Run: TaskList — find lowest-numbered Phase 2 task with status=pending
   - If no Phase 2 tasks remain pending: announce "Phase 2 complete" and stop the loop
   - Read the relevant spec section for the task you're claiming
   - Mark the task in_progress before any code changes

2. IMPLEMENT (the actual work)
   - Edit/create code under atlas_core/ following the spec verbatim
   - Use type hints (Python 3.10+ syntax: list[X], dict[K,V], X | None)
   - Match existing code style (ruff line length 120, double quotes, async-first)
   - Reuse existing modules — never duplicate logic that already lives in atlas_core
   - When in doubt about an architectural decision, default to the spec; if the spec is silent, default to the simplest solution and add a TODO comment

3. TEST (mandatory before commit)
   - Add unit tests under tests/unit/ for any new module
   - Add integration tests under tests/integration/ if Neo4j is involved
   - Run: source .venv/bin/activate && PYTHONPATH="." pytest tests/ -v
   - All tests must pass before committing — no exceptions
   - If a test fails for reasons unrelated to your change (e.g., missing API key), mark it skip with reason; if it fails for a real reason, fix the code

4. COMMIT (clean, documented)
   - Stage with git add .
   - Commit message format:
       "Phase 2 W{N}: {task description}
        
        - Bullet list of what was added/changed
        - Reference spec section being implemented
        - Test count delta (e.g., 'Tests: 59 -> 67')
        Implements Task #{ID}."
   - Use HEREDOC for multiline commit messages
   - Sign with: -c user.email="rich@strategicprofits.com" -c user.name="Richard Schefren"

5. UPDATE TASKS
   - Mark the in_progress task completed
   - If you discovered new follow-up work during implementation, create new tasks for it (don't bury it in TODOs)

6. REPORT (terse — under 150 words)
   - One sentence: what you built
   - Tests pass count
   - Commit hash
   - Next pending task you'd pick up
   - Any flag for Rich's judgment (architectural decisions you punted on)

7. SCHEDULE NEXT WAKEUP
   - If task was small (< 200 LOC, < 30 min real-time): schedule next iteration in 60-120 seconds
   - If task was medium (200-600 LOC, 30-90 min): schedule next iteration in 270 seconds (within cache TTL)
   - If task was large (600+ LOC or required deep thinking): schedule next iteration in 1200-1800 seconds
   - If you hit a blocker requiring Rich's judgment: do NOT schedule, exit the loop and surface the question

STOP-AND-WAKE-RICH CONDITIONS (do NOT continue past these):
- Architectural decision not specified in any spec doc and not obvious
- API design choice with downstream implications (e.g., method signatures on the public MCP surface)
- Need to add a new dependency to pyproject.toml beyond what's already pinned
- Test failure that suggests the spec itself is wrong
- Successfully completed Task #31 (Phase 2 done — time for Rich to launch)
- Three consecutive iterations without commits (loop is stuck)

ANTI-PATTERNS TO AVOID:
- Do NOT skip writing tests — every module gets tested
- Do NOT mock Neo4j when integration tests can use the live container
- Do NOT modify upstream Graphiti code — only subclass/override
- Do NOT add new top-level entities to the ontology — Phase 1 is locked at 8
- Do NOT change the AGM operator semantics without updating both the spec and the compliance suite
- Do NOT commit if any test fails
- Do NOT skip the "mark task in_progress" step — it's how Rich sees what you're working on

QUALITY BAR:
- Every public function has a docstring with spec reference
- Every magic number has a named constant
- Every Cypher query is tested against the live Neo4j container
- Every commit can be reverted cleanly
- Code that ships in this repo is the code that ships in the public launch repo — write it like the world will read it

When you start: orient first, claim a task, implement, test, commit, report, schedule. No exceptions to the protocol.
```

---

## TO START THE LOOP

1. Verify Neo4j is running:
   ```bash
   docker ps --filter name=neo4j-atlas
   # Should show "Up X minutes (healthy)"
   ```

2. Start the loop in Claude Code by pasting the **LOOP COMMAND** block above.

3. Claude will execute one task per iteration, commit, and self-schedule the next wake-up.

## TO MONITOR PROGRESS

```bash
# See commits as they happen
cd ~/Projects/atlas/build/atlas && git log --oneline

# See tests passing
cd ~/Projects/atlas/build/atlas && source .venv/bin/activate && pytest tests/ -v

# See task status
# (Tasks visible in Claude Code task list)
```

## TO STOP THE LOOP

Type `stop loop` or `cancel loop` to Claude. The current iteration completes, no new wakeup is scheduled.

## EXPECTED COMPLETION

15 Phase 2 tasks queued. Average 1-2 hours per task with Codex assistance, ~4-6 hours per task for the algorithmically dense ones (Ripple, AGM operators, BusinessMemBench). Expected wall-clock: 5-7 days of loop iterations to complete Phase 2.
