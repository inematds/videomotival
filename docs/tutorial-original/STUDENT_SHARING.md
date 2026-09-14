# Sharing this tutorial safely

Do not send the project folder directly. It contains a local `.env` file with
private Fish Audio credentials.

Create a clean student archive from the project root:

```sh
./scripts/create-student-package.sh
```

The archive is written to `dist/motivational-video-student.zip`. By default it
contains the tutorial skill, its scripts and templates, this guide, and the safe
`.env.example` placeholder. It does not contain `.env`, generated output, Git
history, macOS metadata, caches, or common private-key file types.

To include the example video and its generated working files:

```sh
./scripts/create-student-package.sh --include-output
```

The exporter checks the staged package for any exact credential values from the
local `.env` and for common high-confidence secret formats before creating the
ZIP. If a check fails, do not share the archive; inspect the named file and
remove or rotate the credential first.

Each student should copy `.env.example` to `.env` and enter credentials issued
for that student. Never distribute one shared instructor API key. Prefer
restricted, low-quota teaching credentials when the provider supports them.

Before uploading, inspect the ZIP contents:

```sh
unzip -l dist/motivational-video-student.zip
```

If this folder or its `.env` has ever been uploaded, committed, emailed, or
shared through cloud storage, excluding it later is not sufficient. Revoke and
replace the exposed key, then remove it from the remote service or history.

