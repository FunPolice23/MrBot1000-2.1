# MrBot1000 operator runbook

## Safe first startup

1. Create and activate the project virtual environment.
2. Install `requirements.txt`.
3. Start with `python main.py --safe-mode`.
4. Confirm the startup log reports the configured providers and no database
   initialization errors.
5. Keep `MRBOT_SAFE_MODE=true` enabled until provider connectivity and approval
   behavior have been verified.

## Provider configuration

Configure providers through the Settings surface or `.env` using the examples
in `.env.example`. Never paste API keys into prompts, workshop files, logs, or
source control. Use the redacted diagnostics exposed by the dual-brain runtime
when reporting configuration problems.

Before enabling a provider, verify:

- The endpoint is reachable.
- The selected model exists.
- The model supports the required chat/streaming/tool features.
- The provider's role is explicitly enabled.
- Cloud spending limits are configured.

## Approval workflow

Mutating tools and external commitments must remain pending until a human
reviews the request details, arguments, target, and expected side effects.
Reject requests with unclear targets, unsupported claims, credential handling,
or unexpected payment/account actions.

Model narration is not execution evidence. Only dispatcher-confirmed tool
results and independently verified external evidence count.

## Autonomous operation

Start with bounded settings:

```text
MRBOT_AUTONOMY_MAX_CONCURRENT=1
MRBOT_AUTONOMY_MAX_RUN_SECONDS=900
MRBOT_SAFE_MODE=true
```

Increase concurrency only after recovery tests and provider rate limits have
been validated. A cancelled or interrupted run must remain failed until a
human reviews whether it is safe to retry.

## Backups and recovery

Back up all authoritative SQLite stores together:

- `agent.db`
- `earning.db`
- `earning_memory.db`
- `opportunity_portfolio.db`
- `autonomous_runs.db`

Stop the application before copying databases. Preserve WAL sidecar files when
present. After restoring, start in safe mode and inspect reconciliation and
startup warnings before resuming work.

## Live financial capabilities

Keep live trading, wallet, payout, and account actions disabled by default.
Before enabling any of them:

1. Confirm credentials are present only in the approved secret store.
2. Confirm current market or platform data is available.
3. Confirm deterministic risk limits.
4. Confirm human approval is required for the intended action.
5. Perform a dry run and inspect the resulting evidence.

Never treat a model claim, local balance estimate, or manual assertion as
verified payment.

## Emergency stop

For an immediate stop:

1. Reject all pending approval requests.
2. Close the MrBot1000 window cleanly if possible.
3. Terminate only the specific provider/autonomy process shown in the GUI.
4. Set `MRBOT_SAFE_MODE=true` before restarting.
5. Inspect autonomous-run and reconciliation records before retrying.

Do not delete databases to clear a stuck run; the durable failure record is
needed to prevent unsafe replay.

## Diagnostics to collect

When reporting an incident, collect:

- Application version and commit.
- Redacted provider diagnostics.
- Startup warnings.
- Run ID and opportunity ID.
- Approval request ID, if applicable.
- Reconciliation conflicts.
- The smallest relevant test-category result.

Do not include API keys, wallet material, raw credentials, or private model
prompt contents in an incident report.
