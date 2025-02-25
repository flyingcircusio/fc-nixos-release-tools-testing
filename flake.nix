{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";

  outputs = { self, nixpkgs, ... }:
    let
      supportedSystems = [ "x86_64-linux" "x86_64-darwin" "aarch64-linux" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in
    {
      packages = forAllSystems (system: let
        pkgs = nixpkgs.legacyPackages.${system};
        pypkgs = pkgs.python3.pkgs;
      in {
        default = pypkgs.buildPythonApplication {
          name = "release";
          src = ./.;
          pyproject = true;
          build-system = [ pypkgs.setuptools-scm ];
          nativeCheckInputs = [
            pypkgs.pytestCheckHook
          ];
          dependencies = [
            pypkgs.python-dateutil
            pypkgs.gql
            pypkgs.gql.optional-dependencies.requests
            pypkgs.pydantic
            pypkgs.setuptools
            pypkgs.gitpython
            pypkgs.requests
            pypkgs.pygithub
            pypkgs.rich
            pkgs.gh
          ];
        };
      });

      devShells = forAllSystems (system: let
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        default = pkgs.mkShell {
          packages = [ pkgs.gh ];
        };
      });
    };
}
