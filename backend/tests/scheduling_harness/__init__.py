"""An independent test harness for the monthly schedule generator.

The harness builds problem instances (:mod:`.instances`), judges any roster
against the rules written down in ``schedule_generation_model.md`` and the
constraint settings (:mod:`.oracle`), solves small instances a second way
(:mod:`.reference`), runs the solver under test (:mod:`.runner`), writes
instances into a database the way the application stores them
(:mod:`.db_builder`), builds multi-step situations -- fill-in, mid-month
regeneration, chained months (:mod:`.scenarios`) -- and lists the solver
bugs it has found (:mod:`.known_bugs`). See ``README.md`` beside this file.

Nothing here imports the solver's private helpers to judge anything. The
only things taken from ``schedule_generation_service`` are its input and
output types and its two entry points (plus, in observed runs, a wrapper
around its CBC call that only records what each pass ended with); every
rule is re-derived from the documentation in :mod:`.semantics`.
"""
