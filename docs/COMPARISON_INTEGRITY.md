# Valid inputs before release comparison

Matching metadata in two reports is insufficient: both reports could declare an
impossible generation setting or carry the same contradictory budget. Comparison
now validates each complete export before checking whether its settings match
the other export. The workflow, model requests, grader and historical evidence
are unchanged.

## Configuration checks

Each supported export needs its existing evaluation fields, scenario IDs and
canonical `config_hash`. Only the documented configuration fields are accepted;
an unsupported generation option cannot silently escape comparison.

- Provider is `scripted` or `openai`; model and revision are nonempty strings.
  Live evidence requires a recorded revision, not `unrecorded`.
- Temperature is finite and between zero and two. Timeout is finite and between
  one and 120 seconds; generation-token limit is an integer from 128 to 2048.
  Live runs require both limits. Scripted exports may retain their historical
  null limits or valid ambient live settings.
- Thinking is a boolean, repeat count remains an integer from one to five, and
  proposal budget is the integer one or three. Booleans are not integers here.
- The recorded variant order must be the supported alternating order.
- Prompt fingerprints are lowercase SHA-256 strings. Endpoint fingerprints are
  validated when present; genuine older exports did not record that field.

The configuration hash is recomputed from its exact JSON object using sorted keys,
the existing serialization convention and UTF-8. Non-finite values are refused.
A correctly recomputed hash does not make invalid settings valid. A valid changed
setting with a stale hash is also refused. Fields are neither filled in nor
normalized to make a document pass.

When a run includes `engine_options`, it must contain exactly its declared
`max_proposals`, with strict integer type and agreement with the export's budget.
Recorded proposal counts, when present, cannot exceed the guarded budget or the
baseline's single attempt. Genuine historical runs without per-run options remain
supported; no options are invented or written back into those records.

Cross-report mismatch checks still apply after individual validation. Scripted
comparisons continue to ignore differences in unused, valid live-provider
settings. A model-free fixture is not turned into a live-model comparison merely
because older metadata recorded ambient model settings. Valid prompt/source
changes remain visible in the comparison result.

Historical original/challenge release pairs, the hash-pinned evidence archive and
the live inputs embedded in rules controls are checked for compatibility without
rewriting their bytes. Synthetic test reports that intentionally change a valid
configuration update their own test hash, so mismatch tests still test differing
settings rather than accidentally testing stale metadata.

## Publishing derived CLI reports

The comparison command protects both raw input files, including when `--overwrite`
is supplied. Ordinary path, symlink and hardlink aliases are refused. That option
authorizes replacing derived reports only; default publication remains exclusive
and cannot clobber a writer that creates the destination after validation.

Raw JSON decoding rejects duplicate object keys at every nesting level, explicit
non-finite constants and decimal values that overflow to infinity. Contradictory
fields cannot be silently reduced to their final occurrence before configuration
validation. This matches the archive loader's strict input interpretation.

On macOS and Linux the command keeps the opened raw inputs alive and records their
device/inode identities. It opens the output directory once and uses that pinned
directory descriptor for temporary-file creation, destination checks, linking or
replacement, and cleanup. The check immediately before publication compares the
actual destination with the actual opened inputs, not just their current names.

If another operation renames the output directory and replaces its pathname with
a symlink, writes stay in the originally opened directory. They cannot be
redirected through that new parent path into the raw-input directory. The command
detects that the requested output-directory name changed and exits with status
two; completed outputs remain in the originally opened directory. Deterministic
temporary-only tests reproduce this race with and without `--overwrite`.

These publication operations require POSIX directory-handle support and are
tested on macOS locally and Linux through CI. Native Windows publication is not
supported; the project's Linux container or WSL provides the supported interface.

## Boundaries

The JSON and Markdown outputs are individually published as complete files, not
as one atomic two-file transaction. If the second publication fails, the first
derived output may remain. Inputs must not be modified in place while being read;
the recorded input hashes describe the bytes actually read. The directory-handle
protection addresses the demonstrated parent-path redirection race, not every
possible filesystem action by a malicious process with the same user's access.

Configuration hashes and ledger regrading detect inconsistent evidence. They do
not attest authorship, model identity, provider billing or the authenticity of
manually edited exports. Neither raw studies nor their scientific conclusions
are repaired or improved by stricter validation.
