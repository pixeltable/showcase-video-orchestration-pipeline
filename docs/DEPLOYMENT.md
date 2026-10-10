# Deployment and recovery

The media lesson and evidence workspace are local teaching tools. Provider
benchmarks are explicit, paid experiments. Keep their catalog homes and output
directories separate so a lesson cannot replace research data.

## Local operation

Bind the evidence workspace to loopback. It uses generated media and local
transforms, so its first experience requires no provider credentials. Recorded
provider answers remain labelled as observations from their original run.

Use one writer for each local Pixeltable home. Do not mount the same PostgreSQL
data directory into independent writers. Follow the [Pixeltable operations
guide](https://docs.pixeltable.com/howto/deployment/operations) for the supported
topology and provider throttling.

For paid work, keep a run identity, input hashes, configuration, attempt records,
and accounting output together. Set the spending and request limits before
admitting work. A local limit cannot cancel charges for a request already sent,
and missing provider usage makes the final total uncertain. Investigate
interrupted or unknown-cost attempts before allowing more paid work.

## Before hosting a public workspace

Put end-user authentication and authorization on the HTTP layer. Protect media
access and mutations as well as the page itself. Keep provider credentials on
the server; a browser must not receive them. Use HTTPS, private database and
daemon ports, request-body and media-duration limits, and bounded admission.

Choose a retention policy for source videos, derived images/audio, responses,
and attempt records. Document how deletion affects reproducibility. Test denied
access and recovery after restart in the actual hosting environment. The local
workspace is not evidence that a public multi-user deployment is secure.

## Cold backup and restore drill

1. Pause writes and paid experiments. Stop the workspace and its application-owned
   Pixeltable writer and its embedded PostgreSQL database. Confirm the owned
   database has stopped cleanly before copying files; application exit alone is
   insufficient. Check its `pgdata` and database process. Never stop a database
   belonging to another home.
2. Copy the complete Pixeltable home, external source-media directories, run
   exports, and attempt ledgers to access-controlled storage. Include the deployed
   commit, dependency versions, input hashes, and path mapping. Store secrets
   separately from the backup manifest.
3. Restore to an isolated location using matching dependencies. Avoid starting
   paid computations. Preserve media paths or migrate them deliberately.
4. Verify source hashes, frame and audio counts, request IDs, stored decisions,
   and the raw responses and costs for a selected paid run. Read an existing
   decision before changing a rule; then verify that refreshing it reuses the
   restored preparation.
5. Reconcile pending attempts and inspect unknown costs before admitting new
   paid work. Compare the restored observations with the backup manifest before
   resuming the original installation.

Do not copy a live PostgreSQL data directory. Use the [Pixeltable backup
guide](https://docs.pixeltable.com/howto/deployment/security) for online or hosted
backups, and preserve any media stored outside its managed home. Version history
and committed research exports serve different purposes from a recoverable
database backup.

## Verification boundary

An [isolated cold restore drill](validation/2026-10-10-restore.json) on October 10,
2026 preserved the clip, prepared frames/audio, request decisions, and media
hashes. A separate process refreshed only the second request without rerunning
preparation. It restored to the same paths on one machine with matching
dependencies; relocation, paid attempt ledgers, and hosted recovery were outside
the drill. Its source hashes identify the exact graph tested.

The zero-key lesson tests media transforms and selective refresh. Offline tests
and recorded cloud smoke runs cover their documented cases. They do not establish
tenant isolation, a complete current research rerun, or restoration of your
hosting environment. Keep a dated restore-drill record before making deployment
recovery claims.
