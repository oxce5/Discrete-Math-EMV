{
  description = "EMV decision analysis (console + Qt 6 interface)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAll (pkgs: import ./shell.nix { inherit pkgs; });
      packages = forAll (pkgs: {
        discrete = pkgs.writeShellApplication {
          name = "discrete-emv";
          runtimeInputs = [ pkgs.python312 ];
          text = ''
            exec uv run --directory ${self} emv.py "$@"
          '';
        };
      });
    };
}
