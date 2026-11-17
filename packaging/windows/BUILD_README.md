# LungSight Windows packaging

This directory holds the allow-list packaging source for `0.1.0-beta.3`.

- `build_package.py` stages only application modules, approved public assets, model documentation and the five manifest-pinned weights.
- Developer databases, credential keys, uploads, chat records and CT task folders are rejected or omitted.
- `LungSightLauncher.cs` starts the bundled backend/frontend on loopback ports 18001/18000 and terminates only its own process job.
- `installer.iss` creates a per-user Windows installer and preserves `%LOCALAPPDATA%\LungSight` on uninstall.
- `smoke_test.py` uses a synthetic account and a public fixture to validate the installed app.
- `workbench_acceptance.py --payload <path> --output <directory>` tests the bundled Python/Node services in an isolated directory, including real image analysis, synthetic DICOM, notes, reports, and recovery after restarting the owned backend process. This does not test the Windows launcher or installer UI.

Do not reuse an existing build directory for a different release. Use a new versioned staging directory and recalculate all manifests and checksums. Run the frontend production build before staging.
