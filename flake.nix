{
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forEachSystem = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forEachSystem (pkgs: {
        default =
          let
            python = pkgs.python3.withPackages (
              ps: with ps; [
                discordpy
                python-dotenv
                ollama
                aiofiles
              ]
            );
          in
          pkgs.writeShellApplication {
            name = "thing";
            runtimeInputs = [ python ];
            text = "exec python ${self}/bot.py";
          };
      });

      devShells = forEachSystem (pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.python3
            pkgs.uv
          ];
          shellHook = ''
            echo ""
            echo "=> thing dev shell"
            echo ""
            echo "  uv sync         install deps"
            echo "  uv run bot.py   run bot"
            echo ""
          '';
        };
      });
    };
}
