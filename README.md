# Release tooling for fc-nixos

## Usage

Install the [GitHub CLI](https://cli.github.com/)
```bash
./bootstrap.sh
source .venv/bin/activate
./fc-release.py 202X_XX
```

or

```bash
nix run .# -- 202X_XX
```

or

```bash
nix-shell -p python3 -p scriv -p gh
./fc-release.py 202X_XX
```

## Notes:

- NixOS versions without changes will be skipped automatically (see `--help` for default versions)
- Rerunning without pushing will destroy all previous changes
- You can specify which `--steps` to run.
