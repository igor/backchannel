# Operations runbook

## Start and stop

Run the one core service through your service manager or directly during diagnosis:

```bash
backchannel daemon
```

SIGTERM requests clean shutdown: the daemon stops accepting ticks, waits for an
in-flight job, and exits. Do not run a second daemon against the same source stores.

## Pair Signal

```bash
backchannel link signal
```

The command uses a pty because `signal-cli link` block-buffers when piped. It accepts
both current `sgnl://linkdevice` and legacy `tsdevice://` URIs, sends the URI to
`qrencode` on stdin, opens a temporary PNG, and deletes the PNG after confirmation.

## Capture and heartbeat recovery

A missing or stale derive watermark creates `WARNING-whatsapp.md` or
`WARNING-signal.md` in the corpus root. Inspect the relevant source capture command and
store before rebuilding any derivation. A rebuild is safe only for derived output:

```bash
backchannel derive --source whatsapp --rebuild
backchannel transcribe --source signal
backchannel index
```

Never delete or rewrite a source store or spool as a recovery shortcut.

## qmd recovery

The collection name is `backchannel`, rooted at the corpus root with `**/*.md`.
`backchannel index` creates it when missing, then runs `qmd update` and `qmd embed -f`.
Use `qmd cleanup` only when diagnosing qmd itself; it does not alter source stores.

## Private consumers

Private digest, viewer, anonymisation, msgvault, and backup services are not operated by
the daemon. Keep their currently installed plists and retained source templates available
until the step-3 extraction and separately approved host migration.
