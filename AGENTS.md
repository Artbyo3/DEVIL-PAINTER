# DEVIL PAINTER — AGENT GUIDELINES

## RULE ZERO: ZERO COMMENTS OR DOCSTRINGS IN CODE
- **Zero means zero: comments, docstrings, and comment-like standalone strings are strictly forbidden in code. There is no docstring exception.**
- Do not add or retain line, inline, or block comments in any language, including `# ...`, `// ...`, `/* ... */`, HTML comments, PowerShell block comments, or batch `REM`/`::` comments.
- Python module, class, function, and method docstrings are forbidden, whether written with `"""..."""`, `'''...'''`, ordinary single/double quotes, raw strings, or another string-literal spelling.
- Standalone string expressions used as notes, headings, explanations, disabled code, or pseudo-comments are also forbidden, regardless of quoting style. Do not replace a removed comment with a string literal.
- This applies to application source, tests, developer tools, launch scripts, and generated code. Existing comments and docstrings must be removed when encountered; never preserve them merely because they predate this rule.
- Keep explanations, usage instructions, and design rationale in Markdown documentation such as `README.md` or `AGENTS.md`, not inside code. Use descriptive names and straightforward structure to make code self-documenting.
- Actual program data is not a comment: preserve strings that are assigned, returned, passed to functions, or otherwise used by the program, including UI labels, error messages, templates, and generated-script contents. Inspect their purpose instead of blindly deleting every triple-quoted string. Generated-script contents must themselves obey this rule.
- When removing a docstring or comment would leave an empty required code block, retain valid syntax with `pass`.
- Verify Python with both tokenization and AST inspection: reject every `COMMENT` token and every standalone string-expression node, including all docstrings. Tokenization alone is insufficient because Python treats docstrings as strings, not comment tokens. Apply equivalent comment checks to other code languages and generated code, then verify syntax and run the required tests. Do not claim zero comments based only on a `#` search or tokenizer scan.

## RULE ZERO-B: ZERO DEAD CODE AND ZERO UNUSED IMPORTS
- **Dead code and unused imports are strictly forbidden across the codebase.**
- Every import statement must be actively used in the importing file. Never leave unused symbols in `import` or `from ... import ...` statements.
- Every module-level definition (constant, variable, function, class, or dataclass) must be actively referenced in the project or explicitly exported for Blender extension lifecycle registration (`bl_info`, registered scene operators/panels/properties).
- No speculative, abandoned, or placeholder code left behind after consolidation.
- **Import integrity**: every name imported from a project module must exist in that module. A token or constant is defined in its home module before anything references it.
- **Load gate**: no build is verified, ready, or done unless the packaged extension imports and registers cleanly in a real Blender — every module, no mocks. Mocked headless tests never count as evidence for import or UI-registration correctness. Reports list real-Blender checks separately from mocked checks.
- Automated enforcement: `python -m tools.check_dead_code` checks all package modules for unused imports, missing cross-module imports, and unreferenced module-level definitions; `python tools/check_comments.py` enforces Rule Zero; `tests/blender_smoke.py` imports and registers the add-on and packaged extension in real Blender with zero mocks. All are enforced during extension packaging and test runs (`tools/build.py` and `tests/test_checks.py`).

---

## ARTIST-FACING ANSWERS AND FEATURE REVIEWS
- Lead with the recommendation and the artist benefit, not implementation details. Use plain, concise language by default.
- For feature reviews, use "Add [feature] because [practical artist benefit]", "Do not add [feature] because [reason]", or "Prototype [feature] first because [uncertainty]". Explain whether the feature removes a real obstacle when doing layer-based texture painting in Blender.
- Include technical details only when they are necessary to understand the recommendation, a meaningful limitation, or a decision the artist needs to make. Do not default to source paths, function names, plumbing, or implementation walkthroughs.
- Keep build priorities distinct from deferred conveniences and rejected features. Do not turn a review request into authorization to implement features.
- Still verify claims against the source and report uncertainty honestly; concise answers must not hide important risks or imply an untested feature works.
- Keep shipping reports brief while retaining the required verification, package, merge, and cleanup facts. Documentation-only changes do not require an artificial artist test.

## ARCHITECTURE & IMPLEMENTATION PRINCIPLES
- Validation stage: keep the repository focused on clean package layout, Blender 5.2+ extension packaging, static checks, and headless Blender load verification until painting architecture is designed and approved.
- Keep `devil_painter/` strictly for add-on runtime code and manifest, `tests/` for automated unit and Blender smoke tests, and `tools/` for build and verification scripts.
- Never reference proprietary third-party painting or cloth-authoring tool names in any public file.

---

## REQUIRED ARTIST ACCEPTANCE AND SHIPPING WORKFLOW
- The required sequence is: implement -> automated verification -> ready for artist testing -> artist approval -> PR and merge -> verified session closure. Do not replace artist acceptance with automated tests or agent reviews.
- Before handing off for artist testing, finish the requested work, run all unit tests, static checks, and real-Blender package/load verification, verify Rule Zero, and prepare the exact installable build. State what changed, give a short focused test checklist and the build location, and explicitly ask the user to test it. Stop and wait at this acceptance gate; do not open or merge a PR while the build is still awaiting artist acceptance.
- Honor narrower instructions such as "draft PR only", "do not merge", "wait", or "do not push".
- Once shipping is authorized, run `python -m unittest discover -s tests -p "test_*.py" -v`, `python tools/build.py`, `python tools/check_public.py`, `python -m tools.check_dead_code`, and `git diff --check`, verify the package matches the source, and push/merge cleanly targeting `main`.
- Never remove `main`, the default branch, protected/release/long-lived branches, active sessions' branches or worktrees, branches supporting an open PR, or unmerged work.
- Clean disposable scratch after diagnostics and reviews are resolved; preserve `dist/`, required fixtures, and user projects.

## DISPOSABLE ARTIFACT CONTRACT
- Keep installable deliverables in `dist/`; never auto-delete that directory.
- Put every disposable development artifact in ignored `scratch/`: screenshots, crops, test scenes/backups, reports, generated scripts, logs, downloads, and temporary dependencies. Never use the repository root, source folders, or `dist/` as a dumping ground.
- Disable Python bytecode generation (`PYTHONDONTWRITEBYTECODE=1` or `python -B`) for development subprocesses; do not create scattered `__pycache__` directories.
- Cleanup must validate its repository-local target and refuse links/junctions. Never delete source, required assets/licenses, installable ZIPs, or user projects.
- Before handing off finished work, verify the installable ZIP still exists in `dist/` and `scratch/` has been cleaned unless diagnostics are pending.

## WORKING REPORTS AND REPOSITORY ROOT
- Working reports (session reports, benchmarks, diagnoses, verification logs, audits) never live in the repository root — they go in `reports/`.
- The repository root is reserved strictly for product and project configuration files (`README.md`, `LICENSE`, `AGENTS.md`, and top-level configuration). Never place working reports or diagnostic writeups in the root directory.

## PUBLIC HYGIENE
- Keep local git identity configured to `Artbyo3` (`170281415+Artbyo3@users.noreply.github.com`).
- Never commit personal paths, local account names, unapproved email addresses, or credentials. Verify with `python tools/check_public.py`.
