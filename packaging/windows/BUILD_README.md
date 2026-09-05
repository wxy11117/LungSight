# LungSight Windows packaging

This directory holds the allow-list packaging source for `0.1.0-beta.1`.

- `build_package.py` stages only application modules, approved public assets, model documentation and the five manifest-pinned weights.
- Developer databases, credential keys, uploads, chat records and CT task folders are rejected or omitted.
- `LungSightLauncher.cs` starts the bundled backend/frontend on loopback ports 18001/18000 and terminates only its own process job.
- `installer.iss` creates a per-user Windows installer and preserves `%LOCALAPPDATA%\LungSight` on uninstall.
- `smoke_test.py` uses a synthetic account and a public fixture to validate the installed app.

Do not reuse an existing `build-beta1` directory for a different release. Use a new versioned staging directory and recalculate all manifests and checksums.
