# Release tooling for fc-nixos

## Usage

```bash
nix run .# -- 202X_XX
```

or

```bash
nix-shell -p python3 -p scriv -p gh
src/fc_release.py 202X_XX
```

or


Install the [GitHub CLI](https://cli.github.com/) (optional) and
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
fc-release 202X_XX
```


## Notes:

- NixOS versions without changes will be skipped automatically (see `--help` for default versions)
- Rerunning without pushing will destroy all previous changes
- You can specify which `--steps` to run.
