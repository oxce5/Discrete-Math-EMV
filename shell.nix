# nix-shell
#
#   nix-shell                 # classic channel-based shell
#   nix develop               # via flake.nix in this directory
#
# Then, inside the shell:
#   uv sync                   # once, creates .venv with PySide6
#   uv run emv.py --ui        # Qt interface
#   uv run emv.py             # console report

{ pkgs ? import <nixpkgs> { } }:

let
  # Qt's shared libraries: Nix does not put them on the interpreter's search
  # path, so they have to be in the environment (or the app dlopens them).
  qtCore = with pkgs; [
    glib
    libglvnd
    fontconfig
    freetype
    dbus
    libxkbcommon
  ];
  # Everything the "xcb" and "wayland" platform plugins dlopen at startup.
  # Missing any of these makes Qt abort with "no Qt platform plugin could be
  # initialized" (libxcb-cursor0 is the usual culprit).
  # Note: libX11-xcb.so.1 ships inside libX11, there is no separate package.
  linuxDisplay = pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux (
    with pkgs;
    [
      # X11 / xcb
      libX11             # also provides libX11-xcb.so.1
      libXext
      libXrender
      libXfixes
      libXdamage
      libXcomposite
      libxi
      libXcursor
      libXinerama
      libXrandr
      libXxf86vm
      libxcb
      libxcb-util
      libxcb-image
      libxcb-keysyms
      libxcb-render-util
      libxcb-wm          # also provides libxcb-icccm
      libxcb-cursor      # Qt's xcb plugin needs this one
      zstd
      xkeyboard-config
      # wayland
      wayland
      wayland-protocols
    ]
  );
in
pkgs.mkShell {
  name = "discrete-emv";

  packages = [ pkgs.python312 pkgs.uv ] ++ qtCore ++ linuxDisplay;

  shellHook = ''
    # NIX_LDFLAGS is a list of "-L/nix/store/..." flags; turn it into a search path
    _nix_libs=$(printf '%s\n' $NIX_LDFLAGS | sed -n 's/^-L//p' | paste -sd: -)
    export LD_LIBRARY_PATH="''${_nix_libs}''${LD_LIBRARY_PATH:+:}$LD_LIBRARY_PATH"
    unset _nix_libs

    if [ -n "''${DISPLAY:-}" ] && [ -z "''${QT_QPA_PLATFORM:-}" ]; then
      # XWayland is the more reliable path than the wayland plugin
      export QT_QPA_PLATFORM=xcb
    fi

    if [ -z "''${DISPLAY:-}" ] && [ -z "''${WAYLAND_DISPLAY:-}" ]; then
      export QT_QPA_PLATFORM=offscreen
      echo "no display detected: Qt will run headless (use -platform vnc to see it)"
    fi

    echo "discrete: run 'uv sync' once, then 'uv run emv.py --ui'"
  '';
}
