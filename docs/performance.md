# Performance

Cold-start and latency figures for the three Lambda functions. **Status: `NEEDS-AWS`.** Nothing has been
deployed yet, so there is nothing to measure. No figure is published until it has been measured, and a
figure quoted anywhere else (a CV, a talk) has to carry the method below or it does not belong in this project.

## Method

1. Deploy the commit to dev ([runbook](RUNBOOK.md)), with the function at its configured memory and runtime.
2. Force cold starts: change an environment variable (a new execution environment per invocation after a
   configuration change), then invoke the function, repeating until there are at least 30 cold samples.
   Also invoke it repeatedly without changing anything, to collect warm samples.
3. Collect Lambda's own `REPORT` lines and summarise them:

   ```bash
   aws logs tail /aws/lambda/<function-name> --since 1h | python scripts/measure_cold_start.py --markdown --region <region> --runtime python3.12
   ```

4. Paste the row below with the date and the commit it was measured at. Percentiles are nearest-rank and
   unrounded: [scripts/measure_cold_start.py](../scripts/measure_cold_start.py) only reads what Lambda logged.

What is deliberately *not* done: SnapStart (billed for Python) and Powertools (extra packaging and X-Ray cost),
for the reasons in [ADR 0008](adr/0008-runtime-patterns.md). They are worth revisiting only if a row here shows
a cold start that matters. The checker is not user-facing, so only the two API functions are candidates.

## Results

| Run | Date | Region | Memory | Runtime | Invocations | Cold starts | Init p50 (ms) | Init p95 (ms) | Warm p50 (ms) | Warm p95 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|

## Reading the table

- *Init* is the platform's `Init Duration`: loading the runtime and importing the module, before the handler runs.
- *Warm* is the `Duration` of invocations that reused an execution environment.
- Billed duration and memory used are in the script's full output, not in the table.
