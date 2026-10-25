# Slow sections, stopping and shared Codex capacity

A slow early chapter previously held up the visible progress count: the
thread-pool iterator yielded in input order even after later sections completed.
Generation and translation now count completion order. Translation still applies
results in document order so its section/title choices stay deterministic.

Codex requests from this TextFold process are serialized. Generation Stop reaches
the active Codex runner and cancels queued calls before another subprocess starts.
Only the created process tree is terminated: a Windows Job Object or a separate
POSIX process group. There is no process-name search or shared bridge shutdown.
Prompts use a temporary input file so a child that does not read stdin cannot
block cancellation. Completed replies returned before cancellation are still
cached normally. Other agent/API runners retain their existing stop semantics.

Standalone agent children exclude inherited desktop IPC and session control
variables while retaining normal configuration and authentication variables.
Rate-limit errors are not retried as reasoning-effort fallback requests. These
changes reduce contention; they cannot remove provider-side rate limits or
guarantee that another application's requests will not be throttled.

The regression suite uses stand-in model replies and disposable Python child
processes, never a real Codex/bridge process. It checks slow-section completion,
translation progress, environment isolation, queued cancellation, timeout and
large-stdin behavior, reasoning fallback suppression, and preservation of an
unrelated sentinel process when an owned child/grandchild is canceled.

A replay of the cached public source for arXiv 2602.01219 produced 17 sections.
With the second stand-in request held back, progress reached 16/17 before it
was released, then 17/17 afterward. Production storage was opened read-only;
the replay issued no model requests. This verifies progress behavior, not the
latency of a real model request or the cause of every desktop disconnection.
