# MemoryGate design freeze — 2026-11-24 16:42 +08

Written before the sealed test split is opened. Nothing below changes after the test runs start.

## What runs
- Model: gemini-3.5-flash-lite (Vertex, global), temperature 0, thinking budget 0. Config: configs/week1.toml as hashed below.
- Final mode: the learning stream is the whole learn split (766 questions) in 12 rounds; the gate uses val (308), unchanged;
  evaluation is on the sealed test split (460), after rounds 4, 8 and 12 (`--eval-every 4`, only to save credit).
- Groups: no_memory, raw, consolidate, gate_accept, gate_reject. Task orders 0, 1, 2. 15 runs, output in runs/final/.
- All consolidation and gate settings exactly as in development (k 5, 1500 chars, z_crit 1.645, caps, pruning).

## Primary analysis (pre-registered)
`memorygate final-report`: at round 12, per test question correctness is averaged over the 3 orders, and each pair is tested
with a paired z on per-question differences, two-sided, |z| > 1.96. Pairs: each memory group vs no_memory;
raw, gate_accept, gate_reject vs consolidate. Accuracy at rounds 4 and 8 is reported as a curve, not tested.

## Expectations from development data (not used to choose anything on test)
Dev ranking at round 12: raw .597 > consolidate .579 > gate_accept .548 > gate_reject .528 > no_memory .480.
Dev tests: every memory group beat no_memory; raw vs consolidate unclear; both gated groups worse than consolidate.
If test agrees, the conclusion stands as written in the interim report. If not, the test result is reported as is.

## Not run on test
Post-hoc labels and harm injection stay development-only results.

## Frozen files (SHA-256)
    862703482d767d3cafc97da8ff53c1e1ce93ced740a6aba023a1664efa73c5ea  configs/week1.toml
    13f36d1a545c972b6a868f699ab398901c7d8f090501a25403adcc21cf317c71  src/memorygate/__init__.py
    2d5cb0fce2d350e6962ea3fa6fd3048f40d007fbfe9d499773385f667e73f5e8  src/memorygate/analysis.py
    f94a67fa46be69609fc447584ba5d1d69b98ad82c7b0b8ef0bb6047a8b48af44  src/memorygate/cli.py
    ed28cf7c15111cb793d6954ba590a33af462dec9ab735eb2533ba04d851e3855  src/memorygate/config.py
    aefd98b36aec482d8f879879f3a93ddf066879a7aa35cc718c42d545aefe2f6a  src/memorygate/consolidate.py
    dfd5ff9077d1d6616cd110f69f924884045022511d1ae03fb717179c8f5465f3  src/memorygate/data.py
    2186d147dd089553d39d0c63a1279ecc268f00ae5aa47c0d00674eaeffb97204  src/memorygate/gate.py
    f0842739d78c6b0ddcc24c24cb559ae062c074d15c937f0cd4bc7c6777566e29  src/memorygate/grader.py
    8543dfaa6453e6d8dc5fba53f48ad9ed3f4bc610c735574cc42c114c2e9fa9fd  src/memorygate/harm.py
    5de02b13da766c6e883f186072fd7c83b4e7a68f92dd84bfcd4ae9229e7abc73  src/memorygate/llm.py
    814434ca40ed4fcf7b1d18a5db7db901e987803cb9a43217fa29695b55abefcf  src/memorygate/memory.py
    26ac8b87e3c3bd51df74e44815aacc65a2805b42bc6f9da5912706eaa5d779ed  src/memorygate/memstore.py
    5643c80105f2566d7d565afb5983d918fd7c6f0517439fadfe36c8c751440187  src/memorygate/posthoc.py
    ad18f6f95ad5a7c56310f67e684547d51accd886dd78156d93e978cf82ef0555  src/memorygate/prompts.py
    9f5a9bfe1e3a7d5e5a6430cd6e94f734bb0436b116c5fa360627eff0abd5350a  src/memorygate/rounds.py
    df171ac00bebaff5fea0cbd0adbd61d4a16bb25d8fa4a7d6cda3988237040d19  src/memorygate/runner.py
    0406b63b316071cfa4d146ea2051c1677834c97e24f7de2c4066017c6154e03b  src/memorygate/splits.py
    a6a349c2a3c7a6c762de4de4c8ab2006e1ba21454559fc3ec6b861c3371b1973  src/memorygate/sqlexec.py
